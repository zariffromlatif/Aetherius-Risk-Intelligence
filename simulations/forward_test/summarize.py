"""Summarize the forward-test logs into REPORT.md.

Reports what an honest reviewer would ask for:

* how many alerts the model raised per name per week (alert burden),
* how many of them a human judged material (from ``labels.json``),
* optionally (``--prices``), what the stock did in the 5 trading days BEFORE
  and AFTER each flag, so you can see whether flags lead or lag the move.

``labels.json`` maps a flag ``key`` to ``{"material": true|false, "note": "..."}``.
Label flags blind to subsequent price action where you can.

Usage:
    python simulations/forward_test/summarize.py --log-dir simulations/forward_test/log [--prices]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MATERIAL_DRAWDOWN = -0.10


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load_jsonl(paths: list[Path]) -> list[dict]:
    rows = []
    for path in sorted(paths):
        rows += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows


def window_returns(closes: list[tuple[datetime, float]], at: datetime, days: int = 5) -> dict | None:
    """Close-to-close return over ``days`` sessions before and after ``at``.

    ``closes`` is ascending (session_date, close). The flag's own session is the
    last close at or before ``at``. Returns None when there is not enough data.
    """
    idx = max((i for i, (d, _) in enumerate(closes) if d <= at), default=None)
    if idx is None or idx - days < 0 or idx + days >= len(closes):
        return None
    base = closes[idx][1]
    after = [c for _, c in closes[idx + 1 : idx + days + 1]]
    return {
        "before_5d": round(base / closes[idx - days][1] - 1.0, 4),
        "after_5d": round(after[-1] / base - 1.0, 4),
        "max_drawdown_after_5d": round(min(c / base for c in after) - 1.0, 4),
    }


def fetch_closes(ticker: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    """Daily closes from Yahoo's public chart endpoint (best effort, unofficial)."""
    import httpx

    resp = httpx.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        params={"period1": int(start.timestamp()), "period2": int(end.timestamp()), "interval": "1d"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30.0,
    )
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    return [
        (datetime.fromtimestamp(t, tz=timezone.utc), float(c)) for t, c in zip(stamps, closes) if c is not None
    ]


def build_report(runs: list[dict], observations: list[dict], flags: list[dict], labels: dict, prices: dict) -> str:
    L = ["# Aetherius Forward Test — Live Report", ""]
    if not runs:
        return "\n".join(L + ["No runs recorded yet."]) + "\n"
    first, last = runs[0]["recorded_at"], runs[-1]["recorded_at"]
    weeks = max((_parse(last) - _parse(first)).days / 7.0, 1 / 7.0)
    tickers = sorted({o["ticker"] for o in observations} | {f["ticker"] for f in flags})
    L += [
        f"- Runs: {len(runs)} ({first} → {last}), ~{weeks:.1f} weeks",
        f"- Watchlist SHA-256: `{runs[-1]['watchlist_sha256']}`"
        + ("" if len({r['watchlist_sha256'] for r in runs}) == 1 else " **(changed during the test!)**"),
        f"- Matched observations logged: {len(observations)}",
        f"- Shippable flags: {len(flags)} ({len(flags) / weeks:.1f} per week across the whole list)",
        f"- Runs with fetch errors: {sum(1 for r in runs if r['errors'])}",
        "",
        "## Alert burden by name",
        "",
        "| Ticker | Matched obs | Flags | Flags / week | Labeled | Material | Not material |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    obs_by = Counter(o["ticker"] for o in observations)
    flag_by = Counter(f["ticker"] for f in flags)
    for t in tickers:
        own = [f for f in flags if f["ticker"] == t]
        lab = [labels[f["key"]] for f in own if f["key"] in labels]
        mat = sum(1 for x in lab if x.get("material"))
        L.append(
            f"| {t} | {obs_by[t]} | {flag_by[t]} | {flag_by[t] / weeks:.2f} | {len(lab)} | {mat} | {len(lab) - mat} |"
        )
    labeled = [labels[f["key"]] for f in flags if f["key"] in labels]
    L += ["", "## Precision (human-labeled)", ""]
    if labeled:
        mat = sum(1 for x in labeled if x.get("material"))
        L.append(f"{mat} of {len(labeled)} labeled flags judged material ({mat / len(labeled):.0%}). "
                 f"{len(flags) - len(labeled)} flags still unlabeled.")
    else:
        L.append("No flags labeled yet. Add judgments to `labels.json`.")
    if prices:
        L += [
            "",
            "## Price context (5 trading days before / after each flag)",
            "",
            "A flag that mostly follows a fall (negative *before*) is reporting the move, not anticipating it.",
            "",
            "| Ticker | Flag observed | Before 5d | After 5d | Max drawdown after | Title |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        leading = lagging = 0
        for f in flags:
            r = prices.get(f["key"])
            if not r:
                continue
            if r["max_drawdown_after_5d"] <= MATERIAL_DRAWDOWN:
                leading += 1
            if r["before_5d"] <= MATERIAL_DRAWDOWN:
                lagging += 1
            L.append(
                f"| {f['ticker']} | {f['observed_at']} | {r['before_5d']:+.1%} | {r['after_5d']:+.1%} | "
                f"{r['max_drawdown_after_5d']:+.1%} | {(f.get('title') or '')[:70]} |"
            )
        L += ["", f"- Flags followed by a ≥10% drawdown within 5 sessions: {leading}",
              f"- Flags preceded by a ≥10% fall in the prior 5 sessions: {lagging}"]
    L += ["", "_Generated by `simulations/forward_test/summarize.py`. Not investment advice._", ""]
    return "\n".join(L)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log-dir", type=Path, default=HERE / "log")
    parser.add_argument("--labels", type=Path, default=HERE / "labels.json")
    parser.add_argument("--out", type=Path, default=None, help="default: <log-dir>/REPORT.md")
    parser.add_argument("--prices", action="store_true", help="fetch daily closes for price context")
    args = parser.parse_args()

    runs = load_jsonl([args.log_dir / "runs.jsonl"]) if (args.log_dir / "runs.jsonl").exists() else []
    observations = load_jsonl(list(args.log_dir.glob("observations-*.jsonl")))
    flags = load_jsonl(list(args.log_dir.glob("flags-*.jsonl")))
    labels = json.loads(args.labels.read_text(encoding="utf-8")) if args.labels.exists() else {}

    prices: dict[str, dict] = {}
    if args.prices and flags:
        for ticker in sorted({f["ticker"] for f in flags}):
            own = [f for f in flags if f["ticker"] == ticker]
            times = [_parse(f["observed_at"]) for f in own]
            try:
                closes = fetch_closes(ticker, min(times) - timedelta(days=14), max(times) + timedelta(days=14))
            except Exception as exc:  # noqa: BLE001 - price context is optional
                print(f"price fetch failed for {ticker}: {exc}")
                continue
            for f, t in zip(own, times):
                r = window_returns(closes, t)
                if r:
                    prices[f["key"]] = r

    out = args.out or args.log_dir / "REPORT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(runs, observations, flags, labels, prices), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
