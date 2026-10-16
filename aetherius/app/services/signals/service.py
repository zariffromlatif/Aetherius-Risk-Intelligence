from sqlalchemy.orm import Session

from app.models.entities import (
    EvidenceLinks,
    RiskSignals,
    SignalEvidenceRefs,
    SourceObservations,
    WatchlistItems,
    Watchlists,
)
from app.services.scoring.service import (
    ADVERSE_TERMS,
    PRIORITY_SCORE,
    SHIP_SEVERITIES,
    SIGNAL_TYPES,
    ScoreInput,
    adverse_severity,
    compute_brief_priority_score,
    compute_risk_score,
    compute_urgency_score,
    confidence_label,
    infer_signal_type,
    severity_label,
)
from app.utils.time import utcnow

# Scoring constants shared with the backtest harness and the stress-test deck
# (simulations/backtest/run_backtest.py, services/reporting/target_stress_test.py)
# so a live signal and a backtest replay of the same text agree.
_DEFAULT_SOURCE_CONFIDENCE = 0.7
_DEFAULT_FRESHNESS = 0.9
_CROSS_CONFIRMATION = 0.5
_TIME_SENSITIVITY = 0.6
_EVENT_WINDOW_PROXIMITY = 0.6

_SIGNAL_LABELS = {
    "earnings_risk": "earnings risk",
    "guidance_risk": "guidance risk",
    "valuation_compression": "valuation compression",
    "macro_spillover": "macro spillover",
    "regulatory_risk": "regulatory risk",
    "supplier_readthrough": "supplier read-through",
    "customer_readthrough": "customer read-through",
    "liquidity_or_refinancing_risk": "liquidity / refinancing risk",
    "sector_contagion": "sector contagion",
    "balance_sheet_stress": "balance-sheet stress",
}

_WATCH_NEXT = {
    "liquidity_or_refinancing_risk": "Monitor deposit/funding flows, credit spreads, and any capital-raise or facility disclosures.",
    "regulatory_risk": "Monitor regulator statements, filings (8-K), and litigation dockets for escalation.",
    "balance_sheet_stress": "Monitor impairment disclosures, capital ratios, and rating-agency commentary.",
    "guidance_risk": "Monitor revised guidance, pre-announcements, and analyst estimate revisions.",
    "valuation_compression": "Monitor price-target changes, rating actions, and relative multiple drift versus peers.",
    "sector_contagion": "Monitor peer disclosures and sector-wide flows for second-order spread.",
    "supplier_readthrough": "Monitor supplier disclosures for volume, pricing, or continuity changes.",
    "customer_readthrough": "Monitor customer demand commentary and order-book disclosures.",
}
_DEFAULT_WATCH_NEXT = "Monitor follow-through in guidance, demand commentary, and spread behavior."
_INVALIDATION = "Contradictory high-confidence observations within the freshness window, or no follow-through in primary filings."


def _matched_adverse_terms(raw_text: str) -> list[str]:
    low = (raw_text or "").lower()
    return [term for term in ADVERSE_TERMS if term in low]


def score_evidence(
    observation: SourceObservations,
    item: WatchlistItems,
    relevance_score: float,
) -> dict:
    """Deterministically score one evidence link with the backtest's formula."""
    raw_text = observation.raw_text or ""
    event_severity = adverse_severity(raw_text)
    inpt = ScoreInput(
        source_confidence=float(
            observation.source_confidence if observation.source_confidence is not None else _DEFAULT_SOURCE_CONFIDENCE
        ),
        freshness_score=float(
            observation.freshness_score if observation.freshness_score is not None else _DEFAULT_FRESHNESS
        ),
        directness_score=relevance_score,
        cross_confirmation_score=_CROSS_CONFIRMATION,
        watchlist_priority_score=PRIORITY_SCORE.get(item.priority_level, 0.5),
        event_severity_score=event_severity,
        relationship_strength_score=relevance_score,
        time_sensitivity=_TIME_SENSITIVITY,
        event_window_proximity=_EVENT_WINDOW_PROXIMITY,
    )
    risk = compute_risk_score(inpt)
    urgency = compute_urgency_score(inpt, risk)
    priority = compute_brief_priority_score(inpt, risk, urgency)
    severity = severity_label(risk)
    # Same gate as the backtest: a name match on benign content (no adverse
    # language) is never shippable, however direct the match.
    if event_severity == 0.0 and severity in SHIP_SEVERITIES:
        severity = "moderate"
    return {
        "risk_score": risk,
        "urgency_score": urgency,
        "brief_priority_score": priority,
        "severity": severity,
        "confidence": confidence_label(risk),
        "event_severity_score": event_severity,
    }


def is_shippable(scored: dict) -> bool:
    return scored["severity"] in SHIP_SEVERITIES and scored["event_severity_score"] > 0.0


def create_signal_from_evidence(db: Session, evidence: EvidenceLinks) -> RiskSignals:
    item = db.query(WatchlistItems).filter(WatchlistItems.id == evidence.watchlist_item_id).one()
    watchlist = db.query(Watchlists).filter(Watchlists.id == item.watchlist_id).one()
    observation = db.query(SourceObservations).filter(SourceObservations.id == evidence.observation_id).one()

    relevance = float(evidence.relevance_score or 0.0)
    scored = score_evidence(observation, item, relevance)
    sev = scored["severity"]
    # Elevated/high signals must rest on a persisted evidence link carrying a
    # real relevance score.
    if sev in SHIP_SEVERITIES and (evidence.id is None or relevance <= 0.0):
        raise ValueError("Elevated/high signals require a scored evidence reference.")

    sig_type = infer_signal_type(evidence.relationship_type, observation.raw_text)
    if sig_type not in SIGNAL_TYPES:
        sig_type = "macro_spillover"
    label = _SIGNAL_LABELS.get(sig_type, sig_type.replace("_", " "))
    title = (observation.title or "").strip()
    headline = f"{item.ticker}: {label}" + (f" — {title}" if title else "")

    terms = _matched_adverse_terms(observation.raw_text)
    base_why = evidence.evidence_summary or f"{item.ticker} matched via {evidence.relationship_type} mapping."
    if terms:
        why = f"{base_why} Adverse language in source: {', '.join(terms[:6])}."
    else:
        why = f"{base_why} No adverse language detected; held below shippable severity."

    signal = RiskSignals(
        client_id=watchlist.client_id,
        watchlist_item_id=item.id,
        signal_type=sig_type,
        severity_level=sev,
        confidence_level=scored["confidence"],
        risk_score=scored["risk_score"],
        urgency_score=scored["urgency_score"],
        brief_priority_score=scored["brief_priority_score"],
        headline=headline,
        why_it_matters=why,
        pathway=f"{observation.source_name} -> {evidence.relationship_type} mapping -> deterministic score -> prioritization.",
        watch_next=_WATCH_NEXT.get(sig_type, _DEFAULT_WATCH_NEXT),
        invalidation_trigger=_INVALIDATION,
        status="open",
        generated_at=utcnow(),
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)

    ref = SignalEvidenceRefs(risk_signal_id=signal.id, evidence_link_id=evidence.id, rank_order=1)
    db.add(ref)
    db.commit()
    return signal


def signals_for_new_evidence(db: Session, links: list[EvidenceLinks]) -> list[RiskSignals]:
    """Create signals for freshly-mapped evidence links that would ship.

    Non-shippable matches stay as evidence only (visible in the evidence inbox)
    so the review queue is not flooded with benign name mentions.
    """
    created: list[RiskSignals] = []
    for link in links:
        item = db.query(WatchlistItems).filter(WatchlistItems.id == link.watchlist_item_id).one()
        observation = db.query(SourceObservations).filter(SourceObservations.id == link.observation_id).one()
        if is_shippable(score_evidence(observation, item, float(link.relevance_score or 0.0))):
            created.append(create_signal_from_evidence(db, link))
    return created
