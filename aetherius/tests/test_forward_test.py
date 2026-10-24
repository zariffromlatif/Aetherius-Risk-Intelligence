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


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _fake_fetch(fail_first: set[str], fail_always: set[str], clock: _FakeClock, cost: float = 1.0):
    calls: list[str] = []

    def fetch(company_name, **_kwargs):
        clock.t += cost
        calls.append(company_name)
        if company_name in fail_always or (company_name in fail_first and calls.count(company_name) == 1):
            raise RuntimeError("429 Too Many Requests")
        return [{"url": f"https://example.com/{company_name}", "title": f"{company_name} news", "domain": "example.com",
                 "seendate": "20261016T000000Z"}]

    return fetch, calls


GDELT_ITEMS = [{"ticker": t, "company_name": t, "aliases": []} for t in ("AAA", "BBB", "CCC")]
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def test_gdelt_retry_pass_recovers_throttled_names() -> None:
    clock = _FakeClock()
    fetch, calls = _fake_fetch({"BBB"}, set(), clock)
    obs, errors = ft.fetch_gdelt(GDELT_ITEMS, NOW, NOW, None, fetch=fetch, sleep=clock.sleep, clock=clock)
    assert errors == []
    assert calls == ["AAA", "BBB", "CCC", "BBB"]
    assert len(obs) == 3


def test_gdelt_persistent_failure_is_reported_not_silent() -> None:
    clock = _FakeClock()
    fetch, calls = _fake_fetch(set(), {"CCC"}, clock)
    obs, errors = ft.fetch_gdelt(GDELT_ITEMS, NOW, NOW, None, fetch=fetch, sleep=clock.sleep, clock=clock)
    assert calls.count("CCC") == 2
    assert errors == ["gdelt:CCC:429 Too Many Requests"]
    assert len(obs) == 2


def test_gdelt_budget_stops_new_requests_and_names_skipped() -> None:
    clock = _FakeClock()
    fetch, calls = _fake_fetch(set(), set(), clock, cost=100.0)
    obs, errors = ft.fetch_gdelt(
        GDELT_ITEMS, NOW, NOW, None, budget_seconds=150.0, fetch=fetch, sleep=clock.sleep, clock=clock
    )
    assert calls == ["AAA", "BBB"]
    assert errors == ["gdelt:CCC:skipped: run time budget spent"]
    assert clock.t < 150.0 + ft.GDELT_PAUSE_SECONDS + 100.0  # no pointless retry cooldown


def test_gdelt_throttle_text_becomes_a_reported_gap(monkeypatch) -> None:
    # End to end with the real adapter: GDELT's 200/text-plain throttle answer
    # must surface as an error for the name, not as "0 articles, ok".
    import httpx

    from app.services.ingestion import gdelt_adapter

    monkeypatch.setattr(gdelt_adapter.time, "sleep", lambda _s: None)
    throttled = httpx.Response(200, text="Please limit requests to one every 5 seconds.",
                               headers={"content-type": "text/plain"})
    client = httpx.Client(transport=httpx.MockTransport(lambda _req: throttled))
    clock = _FakeClock()
    obs, errors = ft.fetch_gdelt(GDELT_ITEMS[:1], NOW, NOW, client, sleep=clock.sleep, clock=clock)
    assert obs == []
    assert len(errors) == 1 and errors[0].startswith("gdelt:AAA:GDELT still throttling")


def test_report_counts_news_fetch_failures_per_name() -> None:
    runs = [
        {"recorded_at": "2026-10-16T00:00:00Z", "watchlist_sha256": "a", "errors": ["gdelt:NVDA:429 Too Many Requests"]},
        {"recorded_at": "2026-10-17T00:00:00Z", "watchlist_sha256": "a", "errors": ["gdelt:NVDA:429", "edgar:X:no-cik"]},
    ]
    report = summ.build_report(runs, [], [], {}, {})
    assert "| NVDA | 0 | 0 | 0.00 | 0 | 0 | 0 | 2 |" in report
    assert "| X |" not in report


def test_report_lists_every_preregistered_name() -> None:
    runs = [{"recorded_at": "2026-10-16T00:00:00Z", "watchlist_sha256": "a", "errors": []}]
    report = summ.build_report(runs, [], [], {}, {}, ["AAPL", "XOM"])
    assert "| AAPL | 0 | 0 | 0.00 | 0 | 0 | 0 | 0 |" in report
    assert "| XOM |" in report
