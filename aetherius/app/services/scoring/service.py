from dataclasses import dataclass

SIGNAL_TYPES = {
    "earnings_risk",
    "guidance_risk",
    "valuation_compression",
    "macro_spillover",
    "regulatory_risk",
    "supplier_readthrough",
    "customer_readthrough",
    "liquidity_or_refinancing_risk",
    "demand_softness",
    "narrative_break",
    "sector_contagion",
    "sentiment_deterioration",
    "balance_sheet_stress",
    "policy_shock",
    "commodity_input_risk",
}

SEVERITY_RANK = {"low": 0, "moderate": 1, "elevated": 2, "high": 3}
SHIP_SEVERITIES = frozenset({"elevated", "high"})
PRIORITY_SCORE = {"low": 0.2, "normal": 0.5, "high": 0.8, "critical": 1.0}

# Adverse / risk language. A direct mention of a watchlist name is only a
# shippable risk flag when the observation actually carries downside content;
# otherwise a benign product/news mention of the name would false-positive
# (e.g. "Microsoft expands Copilot"). Lower-cased substring match.
#
# Single source of truth for the live signal path, the backtest harness and
# the stress-test deck. Changing it changes the pinned backtest numbers.
ADVERSE_TERMS: tuple[str, ...] = (
    "loss", "losses", "plunge", "plunged", "slid", "slide", "fell", "fall", "drop", "drawdown",
    "downgrade", "downgraded", "withdraw", "withdrawals", "deposit run", "deposit outflow",
    "outflow", "outflows", "liquidity", "squeeze", "contagion", "panic", "fail", "failure",
    "receivership", "collapse", "capital raise", "unrealized loss", "funding pressure",
    "funding costs", "selloff", "sell-off", "warned", "concerns", "stress", "distress",
    "deposit pressure", "reprice", "writedown", "write-down", "default", "insolven",
)

# Content cues used to pick a signal type for a direct match. Checked in order;
# the first type with a matching cue wins. Lower-cased substring match.
_SIGNAL_TYPE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("liquidity_or_refinancing_risk", (
        "liquidity", "deposit run", "deposit outflow", "outflow", "withdrawals", "funding pressure",
        "funding costs", "capital raise", "refinanc", "receivership", "insolven", "default",
    )),
    ("regulatory_risk", (
        "regulator", "investigation", "probe", "subpoena", "lawsuit", "fraud", "sanction",
        "enforcement", "auditor",
    )),
    ("balance_sheet_stress", ("unrealized loss", "writedown", "write-down", "impairment", "balance sheet")),
    ("guidance_risk", ("guidance", "outlook", "forecast cut", "warned")),
    ("valuation_compression", ("downgrade", "downgraded", "price target", "selloff", "sell-off", "plunge")),
    ("sector_contagion", ("contagion",)),
)


def adverse_severity(raw_text: str | None) -> float:
    """Map observation content to an event-severity score in [0, 1].

    Benign text (no risk language) scores 0 so it cannot reach a shippable
    severity on the strength of a name match alone; text with multiple risk
    cues scores high.
    """
    low = (raw_text or "").lower()
    hits = sum(1 for term in ADVERSE_TERMS if term in low)
    if hits == 0:
        return 0.0
    return min(1.0, 0.45 + 0.2 * hits)


def infer_signal_type(relationship_type: str | None, raw_text: str | None = None) -> str:
    """Pick a signal type from the match kind and the observation content."""
    rel = relationship_type or ""
    if rel == "supplier_readthrough":
        return "supplier_readthrough"
    if rel == "customer_readthrough":
        return "customer_readthrough"
    if rel == "sector":
        return "sector_contagion"
    low = (raw_text or "").lower()
    for sig_type, cues in _SIGNAL_TYPE_CUES:
        if any(cue in low for cue in cues):
            return sig_type
    if rel == "direct":
        return "earnings_risk"
    return "macro_spillover"


@dataclass
class ScoreInput:
    source_confidence: float
    freshness_score: float
    directness_score: float
    cross_confirmation_score: float
    watchlist_priority_score: float
    event_severity_score: float
    relationship_strength_score: float
    alert_mode_multiplier: float = 1.0
    novelty_score: float = 0.5
    affected_names_score: float = 0.5
    high_priority_boost: float = 0.0
    time_sensitivity: float = 0.5
    is_new_signal: float = 0.5
    event_window_proximity: float = 0.5
    client_threshold: float = 0.5


def clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def compute_risk_score(v: ScoreInput) -> float:
    base = (
        0.20 * v.source_confidence
        + 0.15 * v.freshness_score
        + 0.20 * v.directness_score
        + 0.15 * v.cross_confirmation_score
        + 0.10 * v.watchlist_priority_score
        + 0.10 * v.event_severity_score
        + 0.10 * v.relationship_strength_score
    )
    return clamp(base * v.alert_mode_multiplier)


def compute_urgency_score(v: ScoreInput, risk_score: float) -> float:
    urgency = (
        0.30 * v.time_sensitivity
        + 0.25 * v.event_severity_score
        + 0.15 * (1.0 - v.client_threshold)
        + 0.15 * v.is_new_signal
        + 0.15 * v.event_window_proximity
    )
    return clamp((urgency + risk_score) / 2.0)


def compute_brief_priority_score(v: ScoreInput, risk_score: float, urgency_score: float) -> float:
    priority = (
        0.40 * risk_score
        + 0.30 * urgency_score
        + 0.15 * v.novelty_score
        + 0.10 * v.affected_names_score
        + 0.05 * (v.high_priority_boost + v.watchlist_priority_score)
    )
    return clamp(priority)


def severity_label(score: float) -> str:
    if score <= 0.35:
        return "low"
    if score <= 0.55:
        return "moderate"
    if score <= 0.75:
        return "elevated"
    return "high"


def confidence_label(score: float) -> str:
    if score < 0.4:
        return "low"
    if score < 0.75:
        return "medium"
    return "high"
