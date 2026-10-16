"""Live forward test of the frozen Aetherius scoring model.

Each run pulls the last ``--hours`` of GDELT news and recent SEC EDGAR filings
for every name in the pre-registered ``watchlist.json``, scores every match with
exactly the same function the historical backtest uses
(``run_backtest._score_observation``), and APPENDS to two monthly logs:

    <log-dir>/observations-YYYY-MM.jsonl   every new matched observation + scores
    <log-dir>/flags-YYYY-MM.jsonl          only the shippable (elevated/high) flags

Nothing is ever rewritten: rows are deduplicated by source key and only new
ones are appended, each stamped with ``recorded_at`` (this run's UTC clock).
Run daily from CI and commit the logs; the git history is then an independent,
timestamped record of what the model said *before* anyone knew the outcome.

Usage:
    python simulations/forward_test/run_forward_test.py --log-dir simulations/forward_test/log
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT / "aetherius", REPO_ROOT / "simulations" / "backtest"):
    if str(p) not in sys.path:
        sys.path.append(str(p))

import httpx  # noqa: E402
from run_backtest import _SHIP_SEVERITIES, _score_observation  # noqa: E402

from app.services.entity_mapping.service import match_item  # noqa: E402
from app.services.ingestion.edgar_adapter import _filing_to_text, parse_submissions  # noqa: E402
from app.services.ingestion.gdelt_adapter import (  # noqa: E402
    DOWNSIDE_DOMAINS,
    _article_to_text,
    _parse_gdelt_seendate,
    fetch_articles,
)

WATCHLIST_PATH = HERE / "watchlist.json"
GDELT_PAUSE_SECONDS = 6.0
GDELT_RETRY_PAUSE_SECONDS = 15.0
GDELT_COOLDOWN_SECONDS = 120.0
GDELT_BUDGET_SECONDS = 40 * 60.0
EDGAR_LOOKBACK_DAYS = 3


def load_watchlist(path: Path = WATCHLIST_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def watchlist_sha256(path: Path = WATCHLIST_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score_observation(obs: dict, items: list[dict]) -> list[dict]:
    """Score one observation against every watchlist item it matches.

    Pure function: same inputs always give the same rows. Uses the backtest's
    scorer unchanged so the forward test evaluates the exact frozen model.
    """
    rows = []
    text_upper = obs["raw_text"].upper()
    for item in items:
        match = match_item(
            text_upper,
            ticker=item["ticker"],
            company_name=item.get("company_name"),
            sector=item.get("sector"),
            aliases=item.get("aliases"),
            relationships=item.get("relationships"),
        )
        if not match:
            continue
        rel, relevance = match
        scored = _score_observation(obs, item, rel, relevance)
        rows.append(
            {
                "key": f"{obs['key']}|{item['ticker']}",
                "ticker": item["ticker"],
                "observed_at": obs["observed_at"],
                "source_type": obs["source_type"],
                "source_name": obs["source_name"],
                "source_url": obs.get("source_url"),
                "title": obs.get("title"),
                "raw_text": obs["raw_text"],
                "shippable": scored["severity"] in _SHIP_SEVERITIES and scored["event_severity_score"] > 0.0,
                **scored,
            }
        )
    return rows


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gdelt_rows(item: dict, articles: list[dict], observations: dict[str, dict]) -> None:
    for a in articles:
        url = (a.get("url") or "").strip()
        if not url or f"gdelt:{url}" in observations:
            continue
        observations[f"gdelt:{url}"] = {
            "key": f"gdelt:{url}",
            "source_type": "news",
            "source_name": a.get("domain") or "GDELT news",
            "source_url": url,
            "title": a.get("title"),
            "raw_text": _article_to_text(item["company_name"], a),
            "observed_at": _iso(_parse_gdelt_seendate(a.get("seendate") or "")),
            "source_confidence": 0.75,
        }


def fetch_gdelt(
    items: list[dict],
    start: datetime,
    end: datetime,
    client: httpx.Client,
    budget_seconds: float = GDELT_BUDGET_SECONDS,
    fetch=fetch_articles,
    sleep=time.sleep,
    clock=time.monotonic,
) -> tuple[list[dict], list[str]]:
    """Fetch GDELT news for every item, with a retry pass and a time budget.

    GDELT throttles shared CI addresses hard. Names that fail the first pass
    are retried once after a cooldown with a longer pause. Once the budget is
    spent no new request starts; every name without news coverage is reported
    in ``errors`` (``gdelt:<TICKER>:...``) so gaps are never silent.
    """
    observations: dict[str, dict] = {}
    last_error: dict[str, str] = {}
    deadline = clock() + budget_seconds
    pending = list(items)
    for attempt, pause in enumerate((GDELT_PAUSE_SECONDS, GDELT_RETRY_PAUSE_SECONDS)):
        if attempt:
            if not pending or clock() >= deadline:
                break
            print(f"gdelt: retrying {len(pending)} name(s) after {GDELT_COOLDOWN_SECONDS:.0f}s cooldown", flush=True)
            sleep(GDELT_COOLDOWN_SECONDS)
        failed = []
        for i, item in enumerate(pending):
            if clock() >= deadline:
                failed += pending[i:]
                for rest in pending[i:]:
                    last_error[rest["ticker"]] = "skipped: run time budget spent"
                break
            if i:
                sleep(pause)
            try:
                articles = fetch(
                    company_name=item["company_name"],
                    window_start=start,
                    window_end=end,
                    aliases=item.get("aliases"),
                    client=client,
                    domain_whitelist=DOWNSIDE_DOMAINS,
                )
            except Exception as exc:  # noqa: BLE001 - one failed name must not abort the run
                last_error[item["ticker"]] = str(exc)
                failed.append(item)
                print(f"gdelt: {item['ticker']} failed (pass {attempt + 1}): {str(exc)[:80]}", flush=True)
                continue
            last_error.pop(item["ticker"], None)
            _gdelt_rows(item, articles, observations)
            print(f"gdelt: {item['ticker']} ok, {len(articles)} article(s) (pass {attempt + 1})", flush=True)
        pending = failed
    errors = [f"gdelt:{item['ticker']}:{last_error[item['ticker']]}" for item in pending]
    return list(observations.values()), errors


def fetch_edgar(items: list[dict], user_agent: str, now: datetime, client: httpx.Client) -> tuple[list[dict], list[str]]:
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    errors: list[str] = []
    try:
        tickers = client.get("https://www.sec.gov/files/company_tickers.json", headers=headers).json()
    except Exception as exc:  # noqa: BLE001
        return [], [f"edgar:tickers:{exc}"]
    cik_by_ticker = {str(r.get("ticker", "")).upper(): str(r["cik_str"]).zfill(10) for r in tickers.values()}
    cutoff = (now - timedelta(days=EDGAR_LOOKBACK_DAYS)).date().isoformat()
    observations = []
    for item in items:
        cik = cik_by_ticker.get(item["ticker"].upper())
        if not cik:
            errors.append(f"edgar:{item['ticker']}:no-cik")
            continue
        try:
            time.sleep(0.2)  # SEC asks for <= 10 req/s
            payload = client.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers).json()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"edgar:{item['ticker']}:{exc}")
            continue
        for f in parse_submissions(payload, cik, limit=20):
            if f["filing_date"] < cutoff:
                continue
            observations.append(
                {
                    "key": f"edgar:{f['accession']}",
                    "source_type": "sec_edgar",
                    "source_name": f"SEC EDGAR {f['form']}",
                    "source_url": f["url"],
                    "title": f"{item['ticker']} {f['form']} {f['filing_date']}",
                    "raw_text": _filing_to_text(item["ticker"], f),
                    "observed_at": f"{f['filing_date']}T00:00:00Z",
                    "source_confidence": 0.95,
                }
            )
    return observations, errors


def existing_keys(log_dir: Path) -> set[str]:
    keys: set[str] = set()
    for path in log_dir.glob("observations-*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                keys.add(json.loads(line)["key"])
    return keys


def append_rows(log_dir: Path, rows: list[dict], recorded_at: datetime, seen: set[str]) -> tuple[int, int]:
    """Append unseen rows to the monthly logs. Returns (observations, flags) written."""
    log_dir.mkdir(parents=True, exist_ok=True)
    month = recorded_at.strftime("%Y-%m")
    stamp = _iso(recorded_at)
    n_obs = n_flags = 0
    with (log_dir / f"observations-{month}.jsonl").open("a", encoding="utf-8") as obs_f, (
        log_dir / f"flags-{month}.jsonl"
    ).open("a", encoding="utf-8") as flag_f:
        for row in sorted(rows, key=lambda r: (r["observed_at"], r["key"])):
            if row["key"] in seen:
                continue
            seen.add(row["key"])
            out = {"recorded_at": stamp, **row}
            obs_f.write(json.dumps(out, sort_keys=True) + "\n")
            n_obs += 1
            if row["shippable"]:
                flag_f.write(json.dumps(out, sort_keys=True) + "\n")
                n_flags += 1
    return n_obs, n_flags


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log-dir", type=Path, default=HERE / "log")
    parser.add_argument("--hours", type=int, default=26, help="GDELT lookback; >24 so daily runs overlap")
    parser.add_argument("--user-agent", default="Aetherius Forward Test zarif@aetheriusresearch.tech")
    parser.add_argument("--skip-gdelt", action="store_true")
    parser.add_argument("--skip-edgar", action="store_true")
    args = parser.parse_args()

    watchlist = load_watchlist()
    items = watchlist["items"]
    now = datetime.now(timezone.utc)
    observations: list[dict] = []
    errors: list[str] = []
    with httpx.Client(timeout=30.0) as client:
        if not args.skip_gdelt:
            obs, errs = fetch_gdelt(items, now - timedelta(hours=args.hours), now, client)
            observations += obs
            errors += errs
        if not args.skip_edgar:
            obs, errs = fetch_edgar(items, args.user_agent, now, client)
            observations += obs
            errors += errs

    rows = [row for obs in observations for row in score_observation(obs, items)]
    n_obs, n_flags = append_rows(args.log_dir, rows, now, existing_keys(args.log_dir))

    run = {
        "recorded_at": _iso(now),
        "watchlist_sha256": watchlist_sha256(),
        "fetched_observations": len(observations),
        "new_matched_rows": n_obs,
        "new_flags": n_flags,
        "errors": errors,
    }
    args.log_dir.mkdir(parents=True, exist_ok=True)
    with (args.log_dir / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(run, sort_keys=True) + "\n")
    print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()
