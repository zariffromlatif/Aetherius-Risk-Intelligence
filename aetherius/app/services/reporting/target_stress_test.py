"""Target Stress-Test Deck data assembly.

Takes a target spec (ticker + counterparties + window) and a list of observations,
runs the production entity-mapping and severity-scoring stack against them, and
returns a structured dict shaped for the deck template at
``aetherius/app/templates/pdf/target_stress_test.html``.

Design notes
------------
This module is a pure function over ``list[dict]`` observations. It does not
touch the database. Callers that want to build a deck from live data should
first ingest observations via the EDGAR / GDELT adapters, query them out of
``SourceObservations``, and pass the flat dicts here. Callers that want to
build a deck against a backtest fixture (e.g. for sample-deck generation)
pass ``observations.jsonl`` rows directly.

The service does NOT:
  * generate LLM narrative
  * make severity decisions outside the deterministic scoring formula
  * apply any filter that isn't documented in the returned ``metadata`` block

That last constraint matters: every number the deck displays must be
reconstructable from the observations dict plus this file. Any technically-
literate reader must be able to run the same pipeline and get bit-identical
numbers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.entity_mapping.service import match_item
from app.services.scoring.service import (
    ADVERSE_TERMS,
    PRIORITY_SCORE,
    SEVERITY_RANK,
    SHIP_SEVERITIES,
    ScoreInput,
    adverse_severity,
    compute_brief_priority_score,
    compute_risk_score,
    compute_urgency_score,
    confidence_label,
    severity_label,
)

# Shared with the live signal path and simulations/backtest/run_backtest.py so
# the deck's shippable-flag definition matches the backtest's exactly.
_SEVERITY_RANK = SEVERITY_RANK
_SHIP_SEVERITIES = SHIP_SEVERITIES
_PRIORITY_SCORE = PRIORITY_SCORE
_ADVERSE_TERMS = ADVERSE_TERMS
_adverse_severity = adverse_severity

_DECK_VERSION = "1.0.0"

# The pinned 3-event track record from the working paper. Any change to the
# fixtures under simulations/backtest/events/ that would drift these numbers
# must trip the tests in aetherius/tests/test_backtest_harness.py first.
TRACK_RECORD_EVENTS: tuple[dict[str, Any], ...] = (
    {"event_id": "svb-2023", "event_name": "SVB regional-bank contagion (Mar 2023)", "affected": 5, "detected": 5, "median_lead_days": 2.34, "false_positives_on_control": 0},
    {"event_id": "wirecard-2020", "event_name": "Wirecard accounting fraud (Jun 2020)", "affected": 1, "detected": 1, "median_lead_days": 6.60, "false_positives_on_control": 0},
    {"event_id": "ftx-2022", "event_name": "FTX crypto counterparty contagion (Nov 2022)", "affected": 3, "detected": 3, "median_lead_days": 7.12, "false_positives_on_control": 0},
)


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _score_one(
    obs: dict[str, Any],
    target_ticker: str,
    company_name: str,
    sector: str | None,
    aliases: list[str] | None,
    relationships: list[dict[str, Any]] | None,
    priority_level: str,
) -> dict[str, Any] | None:
    """Score a single observation against a single target/counterparty item.

    Returns a dict with score fields and match relationship if the observation
    matched the item; ``None`` otherwise. Does NOT filter on 'shippable'
    severity — the caller (``build_deck_data``) applies that gate so it can
    also count non-shippable-but-matched observations for the metadata block.
    """
    text_upper = (obs.get("raw_text") or "").upper()
    match = match_item(
        text_upper,
        ticker=target_ticker,
        company_name=company_name,
        sector=sector,
        aliases=aliases or [],
        relationships=relationships or [],
    )
    if not match:
        return None
    relationship_type, relevance = match
    adverse = _adverse_severity(obs.get("raw_text") or "")
    inpt = ScoreInput(
        source_confidence=float(obs.get("source_confidence") or 0.7),
        freshness_score=0.9,
        directness_score=relevance,
        cross_confirmation_score=0.5,
        watchlist_priority_score=_PRIORITY_SCORE.get(priority_level, 0.5),
        event_severity_score=adverse,
        relationship_strength_score=relevance,
        time_sensitivity=0.6,
        event_window_proximity=0.6,
    )
    risk = compute_risk_score(inpt)
    urgency = compute_urgency_score(inpt, risk)
    priority = compute_brief_priority_score(inpt, risk, urgency)
    return {
        "ticker": target_ticker,
        "relationship_type": relationship_type,
        "relevance": relevance,
        "risk_score": risk,
        "urgency_score": urgency,
        "brief_priority_score": priority,
        "severity": severity_label(risk),
        "confidence": confidence_label(risk),
        "event_severity_score": adverse,
    }


def build_deck_data(
    target: dict[str, Any],
    counterparties: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    window_start: datetime | str,
    window_end: datetime | str,
    engagement_date: datetime | None = None,
    top_evidence_n: int = 8,
) -> dict[str, Any]:
    """Assemble the Target Stress-Test Deck data dict.

    Parameters
    ----------
    target : dict
        Keys: ``ticker`` (required), ``company_name``, ``sector`` (opt),
        ``aliases`` (opt list), ``priority_level`` (default "critical"),
        ``book_context`` (opt), ``thesis`` (opt short paragraph the analyst
        supplies).
    counterparties : list[dict]
        Each item: ``ticker``, ``company_name``, ``relationship_type``
        (e.g. "supplier_readthrough", "peer"), ``strength`` (0-1),
        optional ``sector``, ``aliases``, ``priority_level``.
    observations : list[dict]
        Flat observation dicts with keys ``raw_text``, ``observed_at``,
        ``title``, ``source_name``, ``source_url``, ``source_type``,
        ``source_confidence``.
    window_start, window_end : datetime | str (ISO)
        Analysis window bounds. Observations outside the window are dropped.
    engagement_date : datetime, optional
        Date on the deck cover. Defaults to the max observed_at.
    top_evidence_n : int
        Cap for the top-evidence section.

    Returns
    -------
    dict shaped for aetherius/app/templates/pdf/target_stress_test.html.
    Every numeric value is derived deterministically from the inputs.
    """
    if not target.get("ticker"):
        raise ValueError("target.ticker is required")

    ws = _parse_dt(window_start)
    we = _parse_dt(window_end)
    in_window: list[dict[str, Any]] = []
    for obs in observations:
        try:
            dt = _parse_dt(obs["observed_at"])
        except (KeyError, ValueError):
            continue
        if ws <= dt <= we:
            copy = dict(obs)
            copy["_dt"] = dt
            in_window.append(copy)

    target_priority = target.get("priority_level", "critical")

    # Score every in-window observation against the target and each counterparty.
    # An observation can produce multiple scored rows if it matches more than
    # one item; each row carries its own ticker + relationship.
    scored_rows: list[dict[str, Any]] = []
    for obs in in_window:
        # Target
        row = _score_one(
            obs,
            target_ticker=target["ticker"],
            company_name=target.get("company_name") or target["ticker"],
            sector=target.get("sector"),
            aliases=target.get("aliases"),
            relationships=None,
            priority_level=target_priority,
        )
        if row is not None:
            row["_obs"] = obs
            row["_dt"] = obs["_dt"]
            scored_rows.append(row)

        # Each counterparty
        for cp in counterparties:
            row = _score_one(
                obs,
                target_ticker=cp["ticker"],
                company_name=cp.get("company_name") or cp["ticker"],
                sector=cp.get("sector"),
                aliases=cp.get("aliases"),
                relationships=[
                    {
                        "related_entity_name": target.get("company_name") or target["ticker"],
                        "related_ticker": target["ticker"],
                        "relationship_type": cp.get("relationship_type", "peer"),
                        "strength": cp.get("strength", 0.5),
                    }
                ],
                priority_level=cp.get("priority_level", "normal"),
            )
            if row is not None:
                row["_obs"] = obs
                row["_dt"] = obs["_dt"]
                scored_rows.append(row)

    # Shippable = severity in {elevated, high} AND adverse severity > 0. Same
    # gate as the backtest harness.
    shippable = [
        r for r in scored_rows
        if r["severity"] in _SHIP_SEVERITIES and r["event_severity_score"] > 0.0
    ]

    # Sort timeline chronologically; top-evidence by (severity_rank desc, brief_priority desc, dt desc).
    timeline = sorted(shippable, key=lambda r: r["_dt"])
    top_evidence = sorted(
        shippable,
        key=lambda r: (-_SEVERITY_RANK[r["severity"]], -r["brief_priority_score"], -r["_dt"].timestamp()),
    )[:top_evidence_n]

    peak_rank = max((_SEVERITY_RANK[r["severity"]] for r in shippable), default=-1)
    peak_severity = next((s for s, k in _SEVERITY_RANK.items() if k == peak_rank), None)
    first_flag_dt = min((r["_dt"] for r in shippable), default=None)
    engagement = engagement_date or (max((r["_dt"] for r in scored_rows), default=None)) or datetime.now(timezone.utc)

    # Invalidation markers are deterministic and follow the pivot memo's
    # "what would prove the thesis wrong" framing. Kept short so the analyst
    # can extend them per engagement rather than the template hardcoding them.
    invalidation_markers = _default_invalidation_markers(target)

    return {
        "cover": {
            "target_ticker": target["ticker"],
            "target_name": target.get("company_name") or target["ticker"],
            "sector": target.get("sector"),
            "engagement_date": engagement.date().isoformat() if engagement else None,
            "window_start": ws.date().isoformat(),
            "window_end": we.date().isoformat(),
            "deck_version": _DECK_VERSION,
        },
        "executive_summary": _executive_summary(
            target=target,
            shippable=shippable,
            peak_severity=peak_severity,
            first_flag_dt=first_flag_dt,
            in_window_count=len(in_window),
        ),
        "thesis": target.get("thesis"),
        "dependency_map": {
            "target": {
                "ticker": target["ticker"],
                "name": target.get("company_name") or target["ticker"],
                "sector": target.get("sector"),
                "priority_level": target_priority,
            },
            "counterparties": [
                {
                    "ticker": cp["ticker"],
                    "name": cp.get("company_name") or cp["ticker"],
                    "relationship_type": cp.get("relationship_type", "peer"),
                    "strength": cp.get("strength", 0.5),
                    "sector": cp.get("sector"),
                }
                for cp in counterparties
            ],
        },
        "timeline": [_public_row(r) for r in timeline],
        "top_evidence": [_public_row(r) for r in top_evidence],
        "invalidation_markers": invalidation_markers,
        "track_record": {
            "events": list(TRACK_RECORD_EVENTS),
            "aggregate": {
                "affected_total": sum(e["affected"] for e in TRACK_RECORD_EVENTS),
                "detected_total": sum(e["detected"] for e in TRACK_RECORD_EVENTS),
                "false_positives_total": sum(e["false_positives_on_control"] for e in TRACK_RECORD_EVENTS),
            },
            "note": "Full methodology in docs/working_paper/detection_timing_backtest_2026-07.md",
        },
        "disclaimer": (
            "Aetherius Risk Intelligence provides research and risk-monitoring services. "
            "Analysis is not investment advice and is not a recommendation to buy, sell, "
            "or hold any security. Nothing herein is a forecast or a guarantee of any outcome."
        ),
        "metadata": {
            "observations_in_window": len(in_window),
            "scored_matches": len(scored_rows),
            "target_scored_matches": sum(1 for r in scored_rows if r["ticker"] == target["ticker"]),
            "shippable_flags": len(shippable),
            "peak_severity": peak_severity,
            "first_elevated_flag_at": first_flag_dt.isoformat().replace("+00:00", "Z") if first_flag_dt else None,
            "adverse_terms_taxonomy_size": len(_ADVERSE_TERMS),
        },
    }


def _public_row(r: dict[str, Any]) -> dict[str, Any]:
    """Strip internal fields (leading-underscore keys) and normalize datetimes."""
    obs = r["_obs"]
    return {
        "ticker": r["ticker"],
        "observed_at": r["_dt"].isoformat().replace("+00:00", "Z"),
        "title": obs.get("title") or "",
        "source_name": obs.get("source_name") or "",
        "source_url": obs.get("source_url") or "",
        "source_type": obs.get("source_type") or "",
        "severity": r["severity"],
        "confidence": r["confidence"],
        "risk_score": round(r["risk_score"], 3),
        "urgency_score": round(r["urgency_score"], 3),
        "brief_priority_score": round(r["brief_priority_score"], 3),
        "relationship_type": r["relationship_type"],
    }


def _executive_summary(
    target: dict[str, Any],
    shippable: list[dict[str, Any]],
    peak_severity: str | None,
    first_flag_dt: datetime | None,
    in_window_count: int,
) -> list[str]:
    """Deterministic 3-5 bullet exec summary.

    Purposefully mechanical: every phrase is derivable from the data. Analysts
    who want a narrative summary can add one during human review — the deck
    template renders that as a distinct section, not a replacement for this.
    """
    bullets = [
        (
            f"Reviewed {in_window_count} in-window observations for "
            f"{target.get('company_name') or target['ticker']} ({target['ticker']}) "
            f"and its declared counterparties."
        ),
        (
            f"{len(shippable)} evidence-backed flags at elevated or high severity."
            if shippable
            else "No evidence-backed elevated or high severity flags on the window."
        ),
    ]
    if peak_severity:
        bullets.append(f"Peak severity reached: {peak_severity}.")
    if first_flag_dt:
        bullets.append(
            f"First elevated flag: {first_flag_dt.date().isoformat()} "
            f"({first_flag_dt.strftime('%H:%MZ')})."
        )
    bullets.append(
        "Detection track record on structurally comparable historical events: "
        "9 of 9 affected names detected across SVB-2023, Wirecard-2020, and FTX-2022; "
        "Flags arrived with the market's reaction, not before it: lead time is measured to "
        "formal resolution, not to the price move. False alarms were not tested: the control "
        "names never appear in the backtest corpora."
    )
    return bullets


def _default_invalidation_markers(target: dict[str, Any]) -> list[str]:
    """The three questions a professional reviewer must be able to answer 'yes'
    to before dismissing an elevated / high flag on the target.

    Kept generic on purpose. Analysts extend or replace during review; this is
    the floor, not the ceiling.
    """
    name = target.get("company_name") or target["ticker"]
    return [
        f"Has {name} publicly refuted the specific factual claim(s) in the top evidence?",
        f"Do subsequent primary-source filings from {name} (8-K / press release / material change) "
        f"materially reduce the severity of the disclosed exposure?",
        "Have independent third parties (rating agencies, regulators, primary counterparties) "
        "issued statements that contradict the adverse narrative?",
    ]


# ---------------------------------------------------------------------------
# Rendering + gates
# ---------------------------------------------------------------------------

def _env() -> Environment:
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    return Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html"]))


def render_deck_html(deck_data: dict[str, Any]) -> str:
    """Render the deck data dict to HTML via the target_stress_test template."""
    template = _env().get_template("pdf/target_stress_test.html")
    return template.render(**deck_data)


def deck_quality_gates(deck_data: dict[str, Any], rendered_html: str) -> tuple[bool, list[str]]:
    """Same discipline as delivery.quality_gates, adapted for a per-target deck.

    A deck may not ship if:
      * the required disclaimer tokens are absent from the rendered HTML
      * any ANALYST-SUPPLIED content contains a BANNED_LANGUAGE hype term
      * the metadata reports 0 observations in window (nothing to say)
      * any top-evidence item is missing its source URL (unauditable claim)

    The banned-language check runs against analyst-authored fields only
    (thesis, invalidation markers, evidence titles) — not the rendered HTML,
    because the fixed disclaimer text intentionally contains words like
    "guaranteed" ("not guaranteed to be accurate…") that are safety framing,
    not hype. This mirrors delivery.quality_gates which runs the same check
    on ``item.body`` fields, not on the whole rendered brief.
    """
    # Delayed import to avoid circular dependency: delivery.service imports
    # models, which pulls in the ORM registry; this service should stay pure
    # unless explicitly asked to gate rendered output.
    from app.services.delivery.service import (  # noqa: PLC0415
        _contains_banned,
        disclaimer_present,
    )

    issues: list[str] = []
    if not disclaimer_present(rendered_html):
        issues.append("Rendered deck is missing the required disclaimer tokens.")

    analyst_supplied_fields: list[str] = []
    if deck_data.get("thesis"):
        analyst_supplied_fields.append(deck_data["thesis"])
    analyst_supplied_fields.extend(deck_data.get("invalidation_markers", []) or [])
    for ev in deck_data.get("top_evidence", []) or []:
        if ev.get("title"):
            analyst_supplied_fields.append(ev["title"])
    for field in analyst_supplied_fields:
        if _contains_banned(field):
            issues.append(f"Analyst-supplied content contains banned / hype language: {field[:80]!r}")
            break

    meta = deck_data.get("metadata", {})
    if meta.get("observations_in_window", 0) == 0:
        issues.append("Deck has zero in-window observations; nothing to report.")
    elif meta.get("target_scored_matches", 0) == 0:
        # The primary target was never mentioned in any in-window observation.
        # For a live pull this almost always means the target's fetch returned
        # nothing (rate-limited / bad query) rather than a genuinely quiet name —
        # shipping a deck whose own subject has zero coverage misleads the client.
        issues.append(
            "Primary target has zero scored matches in the window "
            "(likely a rate-limited or empty fetch); coverage is not deliverable."
        )
    for i, ev in enumerate(deck_data.get("top_evidence", [])):
        if not ev.get("source_url"):
            issues.append(f"Top-evidence item {i} is missing source_url (unauditable claim).")
            break
    return (len(issues) == 0, issues)
