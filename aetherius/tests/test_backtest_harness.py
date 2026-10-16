"""Tests for the historical backtest harness (simulations/backtest/run_backtest.py).

These run fully offline against the committed event fixtures and assert the
detection-timing proof behaves correctly and time-safely across the three
events that anchor the credibility artifact: SVB-2023, Wirecard-2020, FTX-2022.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = REPO_ROOT / "simulations" / "backtest"
if str(BACKTEST_DIR) not in sys.path:
    sys.path.append(str(BACKTEST_DIR))

run_backtest_mod = pytest.importorskip("run_backtest")


# ---------------------------------------------------------------------------
# SVB 2023
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def svb_metrics() -> dict:
    return run_backtest_mod.run_backtest("svb-2023", commit="test")


# Kept as `metrics` for existing test compatibility.
metrics = svb_metrics


def test_scores_in_unit_range(metrics: dict) -> None:
    assert 0.0 <= metrics["detection_recall"] <= 1.0
    assert 0.0 <= metrics["mapping_precision"] <= 1.0


def test_detects_svb_with_positive_lead_time(metrics: dict) -> None:
    """The core claim: we flag SIVB BEFORE the FDIC receivership date."""
    sivb = next((d for d in metrics["detections"] if d["ticker"] == "SIVB"), None)
    assert sivb is not None, "SIVB should be detected in the SVB event"
    assert sivb["lead_time_hours"] > 0, "SIVB must be flagged before the realized event date"
    assert sivb["reached_expected_severity"] is True


def test_detects_majority_of_affected_names(metrics: dict) -> None:
    assert metrics["detection_recall"] >= 0.6, "Should flag most of the affected regional banks"


def test_no_false_positive_on_control_name(metrics: dict) -> None:
    """MSFT appears only in benign product news and must not be flagged elevated/high."""
    assert "MSFT" not in metrics["false_positive_tickers"]
    assert metrics["false_positive_count"] == 0


def test_time_safety_lead_time_never_negative(metrics: dict) -> None:
    for d in metrics["detections"]:
        assert d["lead_time_hours"] >= 0, f"{d['ticker']} flagged after its realized event (future leakage)"


def test_median_lead_time_reported(metrics: dict) -> None:
    assert metrics["median_lead_time_days"] >= 0.0
    # Real GDELT-scraped corpus, so exact size will drift as reruns pick up
    # slightly different articles; assert only that the corpus is materially
    # populated (not the 10-row hand-curated stub the fixture was born as).
    assert metrics["observation_count"] >= 20


# ---------------------------------------------------------------------------
# Wirecard 2020
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wirecard_metrics() -> dict:
    return run_backtest_mod.run_backtest("wirecard-2020", commit="test")


def test_wirecard_detects_wdi_with_positive_lead(wirecard_metrics: dict) -> None:
    """WDI must be flagged before the insolvency filing on 2020-06-25."""
    wdi = next((d for d in wirecard_metrics["detections"] if d["ticker"] == "WDI"), None)
    assert wdi is not None, "WDI should be detected in the Wirecard event"
    assert wdi["lead_time_hours"] > 0
    assert wdi["reached_expected_severity"] is True


def test_wirecard_no_false_positive_on_dte(wirecard_metrics: dict) -> None:
    """DTE (Deutsche Telekom) is the unrelated DAX control and must not be flagged."""
    assert "DTE" not in wirecard_metrics["false_positive_tickers"]
    assert wirecard_metrics["false_positive_count"] == 0


def test_wirecard_recall_full(wirecard_metrics: dict) -> None:
    assert wirecard_metrics["detection_recall"] == 1.0


# ---------------------------------------------------------------------------
# FTX 2022
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ftx_metrics() -> dict:
    return run_backtest_mod.run_backtest("ftx-2022", commit="test")


def test_ftx_detects_silvergate_with_positive_lead(ftx_metrics: dict) -> None:
    """Silvergate (SI) is the highest-exposure public equity in the FTX blast
    radius; it must be flagged before the FTX Chapter 11 filing on 2022-11-11.
    """
    si = next((d for d in ftx_metrics["detections"] if d["ticker"] == "SI"), None)
    assert si is not None, "SI should be detected in the FTX event"
    assert si["lead_time_hours"] > 0
    assert si["reached_expected_severity"] is True


def test_ftx_no_false_positive_on_msft(ftx_metrics: dict) -> None:
    """MSFT is the non-crypto control and must not be flagged on FTX-week news."""
    assert "MSFT" not in ftx_metrics["false_positive_tickers"]
    assert ftx_metrics["false_positive_count"] == 0


def test_ftx_recall_full(ftx_metrics: dict) -> None:
    assert ftx_metrics["detection_recall"] == 1.0
