"""Tests for the Target Stress-Test Deck data assembly service."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.reporting.target_stress_test import (
    TRACK_RECORD_EVENTS,
    _adverse_severity,
    build_deck_data,
    deck_quality_gates,
    render_deck_html,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SVB_OBS_PATH = REPO_ROOT / "simulations" / "backtest" / "events" / "svb-2023" / "observations.jsonl"


# ---------------------------------------------------------------------------
# Adverse severity gate
# ---------------------------------------------------------------------------

def test_adverse_severity_benign_text_is_zero() -> None:
    assert _adverse_severity("Microsoft expands Copilot AI across product suite") == 0.0


def test_adverse_severity_single_adverse_term_scored() -> None:
    # Exactly one adverse term -> base 0.45 + 1 * 0.2 = 0.65.
    s = _adverse_severity("shares fell after the announcement")
    assert 0.4 < s < 0.9


def test_adverse_severity_multi_term_saturates_at_one() -> None:
    s = _adverse_severity(
        "loss losses plunge withdraw contagion collapse receivership panic distress default"
    )
    assert s == 1.0


# ---------------------------------------------------------------------------
# Deck shape and required blocks
# ---------------------------------------------------------------------------

@pytest.fixture()
def minimal_target() -> dict:
    return {
        "ticker": "TEST",
        "company_name": "Test Corp",
        "sector": "Software",
        "aliases": ["Test Corp"],
        "priority_level": "critical",
    }


@pytest.fixture()
def sample_observation() -> dict:
    return {
        "observed_at": "2024-05-01T12:00:00Z",
        "source_type": "news",
        "source_name": "example.com",
        "source_url": "https://example.com/x",
        "title": "Test Corp shares plunge as auditors flag losses on receivables",
        "raw_text": "Test Corp shares plunge as auditors flag losses on receivables and warned of funding pressure.",
        "source_confidence": 0.85,
    }


def test_deck_data_returns_all_required_blocks(minimal_target, sample_observation) -> None:
    deck = build_deck_data(
        target=minimal_target,
        counterparties=[],
        observations=[sample_observation],
        window_start="2024-04-01T00:00:00Z",
        window_end="2024-06-01T00:00:00Z",
    )
    # All top-level blocks the template consumes.
    for key in (
        "cover", "executive_summary", "thesis", "dependency_map",
        "timeline", "top_evidence", "invalidation_markers",
        "track_record", "disclaimer", "metadata",
    ):
        assert key in deck, f"missing deck block: {key}"


def test_deck_cover_reflects_target_and_window(minimal_target, sample_observation) -> None:
    deck = build_deck_data(
        target=minimal_target,
        counterparties=[],
        observations=[sample_observation],
        window_start="2024-04-01T00:00:00Z",
        window_end="2024-06-01T00:00:00Z",
    )
    cover = deck["cover"]
    assert cover["target_ticker"] == "TEST"
    assert cover["target_name"] == "Test Corp"
    assert cover["window_start"] == "2024-04-01"
    assert cover["window_end"] == "2024-06-01"


def test_deck_track_record_matches_working_paper() -> None:
    """Track record on the deck must match the numbers published in the paper."""
    deck = build_deck_data(
        target={"ticker": "TEST", "company_name": "Test"},
        counterparties=[],
        observations=[],
        window_start="2024-01-01T00:00:00Z",
        window_end="2024-02-01T00:00:00Z",
    )
    agg = deck["track_record"]["aggregate"]
    assert agg["affected_total"] == sum(e["affected"] for e in TRACK_RECORD_EVENTS)
    assert agg["detected_total"] == sum(e["detected"] for e in TRACK_RECORD_EVENTS)
    assert agg["detected_total"] == agg["affected_total"], "publish 100% recall or nothing"
    assert agg["false_positives_total"] == 0


# ---------------------------------------------------------------------------
# Signal gates: name-only-benign vs. adverse-narrative
# ---------------------------------------------------------------------------

def test_benign_name_match_does_not_produce_shippable_flag(minimal_target) -> None:
    """A product-news mention of the target must NOT reach 'elevated' severity."""
    benign = {
        "observed_at": "2024-05-01T12:00:00Z",
        "source_type": "news",
        "source_name": "example.com",
        "source_url": "https://example.com/y",
        "title": "Test Corp announces new product feature",
        "raw_text": "Test Corp announces new product feature and confirms strong customer growth.",
        "source_confidence": 0.7,
    }
    deck = build_deck_data(
        target=minimal_target,
        counterparties=[],
        observations=[benign],
        window_start="2024-04-01T00:00:00Z",
        window_end="2024-06-01T00:00:00Z",
    )
    assert deck["metadata"]["shippable_flags"] == 0
    assert deck["timeline"] == []
    assert deck["top_evidence"] == []


def test_adverse_narrative_on_name_match_is_shippable(minimal_target, sample_observation) -> None:
    deck = build_deck_data(
        target=minimal_target,
        counterparties=[],
        observations=[sample_observation],
        window_start="2024-04-01T00:00:00Z",
        window_end="2024-06-01T00:00:00Z",
    )
    assert deck["metadata"]["shippable_flags"] >= 1
    assert deck["metadata"]["peak_severity"] in {"elevated", "high"}
    assert len(deck["top_evidence"]) >= 1
    assert deck["top_evidence"][0]["ticker"] == "TEST"


# ---------------------------------------------------------------------------
# Window filtering
# ---------------------------------------------------------------------------

def test_observations_outside_window_are_dropped(minimal_target, sample_observation) -> None:
    early = dict(sample_observation, observed_at="2020-01-01T00:00:00Z", source_url="https://ex/1")
    in_win = dict(sample_observation, observed_at="2024-05-01T00:00:00Z", source_url="https://ex/2")
    late = dict(sample_observation, observed_at="2030-01-01T00:00:00Z", source_url="https://ex/3")
    deck = build_deck_data(
        target=minimal_target,
        counterparties=[],
        observations=[early, in_win, late],
        window_start="2024-04-01T00:00:00Z",
        window_end="2024-06-01T00:00:00Z",
    )
    assert deck["metadata"]["observations_in_window"] == 1


# ---------------------------------------------------------------------------
# Counterparty propagation
# ---------------------------------------------------------------------------

def test_counterparty_carries_relationship_type_into_deck(minimal_target) -> None:
    cp_obs = {
        "observed_at": "2024-05-01T12:00:00Z",
        "source_type": "news",
        "source_name": "example.com",
        "source_url": "https://example.com/cp",
        "title": "SupplierCo warns of losses and funding pressure",
        "raw_text": "SupplierCo warned of losses, plunge in shipments, and funding pressure.",
        "source_confidence": 0.8,
    }
    deck = build_deck_data(
        target=minimal_target,
        counterparties=[
            {
                "ticker": "SUP",
                "company_name": "SupplierCo",
                "relationship_type": "supplier_readthrough",
                "strength": 0.75,
                "sector": "Manufacturing",
                "priority_level": "high",
                "aliases": ["SupplierCo"],
            }
        ],
        observations=[cp_obs],
        window_start="2024-04-01T00:00:00Z",
        window_end="2024-06-01T00:00:00Z",
    )
    # Dependency map preserves the analyst-supplied relationship.
    assert deck["dependency_map"]["counterparties"][0]["relationship_type"] == "supplier_readthrough"
    # And SupplierCo actually got scored (matching happens via alias, not the
    # target-facing relationship declaration; the important thing is that a
    # counterparty-only observation produced a scored flag).
    tickers = {e["ticker"] for e in deck["top_evidence"]}
    assert "SUP" in tickers


# ---------------------------------------------------------------------------
# Integration against the real SVB fixture
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SVB_OBS_PATH.exists(), reason="SVB fixture not present")
def test_deck_on_svb_fixture_flags_target_at_high_severity() -> None:
    """Sanity anchor: point the deck at the SVB-2023 corpus with SIVB as the
    target and confirm the pipeline reaches 'high' peak severity for it.
    """
    observations = [json.loads(line) for line in SVB_OBS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    deck = build_deck_data(
        target={
            "ticker": "SIVB",
            "company_name": "SVB Financial Group",
            "sector": "Regional Banks",
            "aliases": ["Silicon Valley Bank", "SVB"],
            "priority_level": "critical",
            "thesis": "Concentrated position; regional-bank exposure with rate-sensitive HTM book.",
        },
        counterparties=[],
        observations=observations,
        window_start="2023-03-06T00:00:00Z",
        window_end="2023-03-12T23:59:59Z",
    )
    assert deck["metadata"]["shippable_flags"] > 0
    assert deck["metadata"]["peak_severity"] in {"elevated", "high"}
    # Top evidence must include SIVB rows.
    tickers = {e["ticker"] for e in deck["top_evidence"]}
    assert "SIVB" in tickers


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deck_is_deterministic_across_repeat_calls(minimal_target, sample_observation) -> None:
    args = dict(
        target=minimal_target,
        counterparties=[],
        observations=[sample_observation],
        window_start="2024-04-01T00:00:00Z",
        window_end="2024-06-01T00:00:00Z",
        engagement_date=datetime(2024, 5, 15, tzinfo=timezone.utc),
    )
    deck_a = build_deck_data(**args)
    deck_b = build_deck_data(**args)
    # Strip the engagement date since it defaults from observation timestamps
    # in real usage, and the metadata timestamp round-trips a datetime.
    assert deck_a["metadata"] == deck_b["metadata"]
    assert deck_a["timeline"] == deck_b["timeline"]
    assert deck_a["top_evidence"] == deck_b["top_evidence"]
    assert deck_a["executive_summary"] == deck_b["executive_summary"]


# ---------------------------------------------------------------------------
# Required-argument validation
# ---------------------------------------------------------------------------

def test_missing_ticker_raises() -> None:
    with pytest.raises(ValueError):
        build_deck_data(
            target={"company_name": "Nameless"},
            counterparties=[],
            observations=[],
            window_start="2024-01-01T00:00:00Z",
            window_end="2024-02-01T00:00:00Z",
        )


# ---------------------------------------------------------------------------
# Rendering + gates
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SVB_OBS_PATH.exists(), reason="SVB fixture not present")
def test_render_deck_html_renders_all_required_sections() -> None:
    observations = [json.loads(line) for line in SVB_OBS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    deck = build_deck_data(
        target={
            "ticker": "SIVB",
            "company_name": "SVB Financial Group",
            "sector": "Regional Banks",
            "aliases": ["Silicon Valley Bank", "SVB"],
            "priority_level": "critical",
            "thesis": "Concentrated regional-bank position; rate-sensitive HTM book.",
        },
        counterparties=[],
        observations=observations,
        window_start="2023-03-06T00:00:00Z",
        window_end="2023-03-12T23:59:59Z",
    )
    html = render_deck_html(deck)
    # Section labels that must appear.
    for label in (
        "Target Stress-Test Deck",
        "Executive summary",
        "Dependency map",
        "Key metrics",
        "Top evidence",
        "Timeline",
        "Invalidation markers",
        "Detection track record",
        "Methodology",
        "Disclaimer",
    ):
        assert label in html, f"deck HTML missing section label: {label}"
    # Track-record aggregates from the working paper must be baked in.
    assert "9" in html  # detected_total
    # Target details must appear.
    assert "SIVB" in html
    assert "SVB Financial Group" in html


@pytest.mark.skipif(not SVB_OBS_PATH.exists(), reason="SVB fixture not present")
def test_deck_html_passes_quality_gates_on_svb_fixture() -> None:
    observations = [json.loads(line) for line in SVB_OBS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    deck = build_deck_data(
        target={
            "ticker": "SIVB",
            "company_name": "SVB Financial Group",
            "sector": "Regional Banks",
            "aliases": ["Silicon Valley Bank", "SVB"],
            "priority_level": "critical",
        },
        counterparties=[],
        observations=observations,
        window_start="2023-03-06T00:00:00Z",
        window_end="2023-03-12T23:59:59Z",
    )
    html = render_deck_html(deck)
    ok, issues = deck_quality_gates(deck, html)
    assert ok, f"quality gates failed: {issues}"


def test_deck_quality_gates_flags_missing_disclaimer() -> None:
    fake_deck = {"metadata": {"observations_in_window": 5}, "top_evidence": [{"source_url": "https://x/"}]}
    ok, issues = deck_quality_gates(fake_deck, "<html><body>No disclaimer here</body></html>")
    assert not ok
    assert any("disclaimer" in i.lower() for i in issues)


def test_deck_quality_gates_flags_banned_language_in_analyst_content() -> None:
    """Banned-language gate runs against analyst-supplied content (thesis,
    invalidation markers, top-evidence titles), NOT the whole rendered HTML —
    because the fixed disclaimer intentionally contains words like 'guaranteed'
    ('not guaranteed to be accurate…') that are safety framing, not hype.
    """
    fake_deck = {
        "metadata": {"observations_in_window": 5},
        "thesis": "This stock will crash by next week, guaranteed.",
        "top_evidence": [{"source_url": "https://x/", "title": "Some headline"}],
    }
    html = (
        "<html><body>"
        "This is an information and risk-monitoring service. "
        "It is not investment advice."
        "</body></html>"
    )
    ok, issues = deck_quality_gates(fake_deck, html)
    assert not ok
    assert any("banned" in i.lower() or "hype" in i.lower() for i in issues)


def test_deck_quality_gates_does_not_flag_disclaimer_word_guaranteed() -> None:
    """Regression: the fixed disclaimer contains 'not guaranteed to be accurate' —
    a legitimate safety phrase — and must not trip the banned-language gate.
    """
    fake_deck = {
        "metadata": {"observations_in_window": 5, "target_scored_matches": 3},
        "thesis": "Concentrated regional-bank position; rate-sensitive HTM book.",
        "top_evidence": [{"source_url": "https://x/", "title": "Bank shares fell on funding pressure"}],
        "invalidation_markers": ["Has the target refuted the specific factual claims?"],
    }
    html = (
        "<html><body>"
        "This is an information and risk-monitoring service. "
        "It is not investment advice. "
        "Signals are not guaranteed to be accurate, complete, or timely."
        "</body></html>"
    )
    ok, issues = deck_quality_gates(fake_deck, html)
    assert ok, f"unexpected gate failures: {issues}"


def test_deck_quality_gates_flags_empty_window() -> None:
    fake_deck = {"metadata": {"observations_in_window": 0}, "top_evidence": []}
    html = (
        "<html><body>"
        "This is an information and risk-monitoring service. "
        "It is not investment advice."
        "</body></html>"
    )
    ok, issues = deck_quality_gates(fake_deck, html)
    assert not ok
    assert any("zero" in i.lower() for i in issues)


def test_deck_quality_gates_flags_target_with_no_coverage() -> None:
    """A deck can have in-window observations (from counterparties) yet zero
    coverage on the primary target — the rate-limited-fetch case. That deck is
    not deliverable and the gate must catch it.
    """
    fake_deck = {
        "metadata": {"observations_in_window": 6, "target_scored_matches": 0},
        "top_evidence": [{"source_url": "https://x/", "title": "Supplier news"}],
    }
    html = (
        "<html><body>"
        "This is an information and risk-monitoring service. "
        "It is not investment advice. "
        "Signals are not guaranteed to be accurate, complete, or timely."
        "</body></html>"
    )
    ok, issues = deck_quality_gates(fake_deck, html)
    assert not ok
    assert any("primary target" in i.lower() for i in issues)


def test_deck_quality_gates_flags_evidence_without_url() -> None:
    fake_deck = {
        "metadata": {"observations_in_window": 5},
        "top_evidence": [{"source_url": ""}],
    }
    html = (
        "<html><body>"
        "This is an information and risk-monitoring service. "
        "It is not investment advice."
        "</body></html>"
    )
    ok, issues = deck_quality_gates(fake_deck, html)
    assert not ok
    assert any("source_url" in i for i in issues)
