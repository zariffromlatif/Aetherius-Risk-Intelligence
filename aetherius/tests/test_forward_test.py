"""Offline tests for the live forward test (simulations/forward_test/)."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FT_DIR = REPO_ROOT / "simulations" / "forward_test"
for p in (FT_DIR, REPO_ROOT / "simulations" / "backtest"):
    if str(p) not in sys.path:
        sys.path.append(str(p))

ft = pytest.importorskip("run_forward_test")
summ = pytest.importorskip("summarize")
run_backtest = pytest.importorskip("run_backtest")

ITEMS = [
    {"ticker": "SIVB", "company_name": "SVB Financial", "aliases": ["Silicon Valley Bank"], "priority_level": "normal"},
    {"ticker": "MSFT", "company_name": "Microsoft", "aliases": [], "priority_level": "normal"},
]


def _obs(key: str, text: str) -> dict:
    return {
        "key": key,
        "source_type": "news",
        "source_name": "example.com",
        "source_url": f"https://example.com/{key}",
        "title": text,
        "raw_text": text,
        "observed_at": "2026-10-16T00:00:00Z",
        "source_confidence": 0.75,
    }


def test_watchlist_is_preregistered_and_well_formed() -> None:
    wl = ft.load_watchlist()
    tickers = [i["ticker"] for i in wl["items"]]
    assert wl["registered_at"] == "2026-10-16"
    assert len(tickers) == len(set(tickers)) == 20
    assert all(i["priority_level"] == "normal" for i in wl["items"])


def test_forward_scoring_is_the_frozen_backtest_scorer() -> None:
    obs = _obs("a", "Silicon Valley Bank shares plunge on deposit outflows and liquidity stress")
    (row,) = ft.score_observation(obs, ITEMS)
    expected = run_backtest._score_observation(obs, ITEMS[0], row["relationship_type"], 0.9)
    assert row["ticker"] == "SIVB"
    assert row["risk_score"] == expected["risk_score"]
    assert row["shippable"] is True


def test_benign_mention_is_logged_but_not_flagged() -> None:
    (row,) = ft.score_observation(_obs("b", "Microsoft expands Copilot across product suite"), ITEMS)
    assert row["ticker"] == "MSFT"
    assert row["shippable"] is False


def test_append_is_deduplicated_and_append_only(tmp_path) -> None:
    rows = ft.score_observation(_obs("a", "Silicon Valley Bank shares plunge on liquidity stress"), ITEMS)
    rows += ft.score_observation(_obs("b", "Microsoft expands Copilot"), ITEMS)
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    assert ft.append_rows(tmp_path, rows, now, ft.existing_keys(tmp_path)) == (2, 1)
    first = (tmp_path / "observations-2026-10.jsonl").read_text(encoding="utf-8")
    assert ft.append_rows(tmp_path, rows, now + timedelta(days=1), ft.existing_keys(tmp_path)) == (0, 0)
    assert (tmp_path / "observations-2026-10.jsonl").read_text(encoding="utf-8") == first
    flag = json.loads((tmp_path / "flags-2026-10.jsonl").read_text(encoding="utf-8"))
    assert flag["recorded_at"] == "2026-10-16T00:00:00Z"


def test_window_returns_before_and_after() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [(start + timedelta(days=i), 100.0 - i) for i in range(20)]
    r = summ.window_returns(closes, start + timedelta(days=10, hours=12))
    assert r["before_5d"] == pytest.approx(90 / 95 - 1, abs=1e-4)
    assert r["after_5d"] == pytest.approx(85 / 90 - 1, abs=1e-4)
    assert summ.window_returns(closes, start + timedelta(days=2)) is None


def test_report_flags_watchlist_changes() -> None:
    runs = [
        {"recorded_at": "2026-10-16T00:00:00Z", "watchlist_sha256": "a", "errors": []},
        {"recorded_at": "2026-10-23T00:00:00Z", "watchlist_sha256": "b", "errors": []},
    ]
    report = summ.build_report(runs, [], [], {}, {})
    assert "changed during the test" in report
