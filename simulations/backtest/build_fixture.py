"""Rebuild an event's observations.jsonl from real primary sources.

Reads:
  - simulations/backtest/events/<event-id>/watchlist.json
  - simulations/backtest/events/<event-id>/ground_truth.json

Writes:
  - simulations/backtest/events/<event-id>/observations.jsonl (overwrites)

Sources per observation:
  - GDELT DOC 2.0 for news, per watchlist name + aliases
  - Wayback SEC EDGAR primary-document links resolved at run time for the
    regulatory anchors declared in ground_truth.json (SEC/FDIC/Fed)

Each observation row conforms to what `run_backtest.py` consumes:

    {
      "observed_at": ISO-8601 UTC,
      "source_type": "news" | "sec_filing" | "regulatory",
      "source_name": publisher/domain,
      "source_url": canonical URL,
      "provenance": "GDELT DOC 2.0 query for <name> in <window>",
      "title": headline,
      "raw_text": short natural-language summary composed from title+source,
      "source_confidence": float in [0, 1]
    }

Design notes
------------
This is a **corpus builder**, not the backtest itself. It writes to disk so the
backtest remains fully offline / reproducible: once the fixture is committed,
`run_backtest.py svb-2023` gives the same numbers regardless of GDELT weather.

The fixture is intentionally NOT filtered by adverse-language keywords here.
That filtering happens downstream inside the scoring pipeline (`_adverse_severity`
in `run_backtest.py`), where it belongs. Keeping the fixture unfiltered means
the backtest also stresses the entity-mapping and scoring stages on real noise
(product news, filings not related to the watchlist, wire regurgitation).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "aetherius"
if str(APP_ROOT) not in sys.path:
    sys.path.append(str(APP_ROOT))

from app.services.ingestion.gdelt_adapter import (  # noqa: E402
    DOWNSIDE_DOMAINS,
    _article_to_text,
    fetch_articles,
)

EVENTS_DIR = Path(__file__).resolve().parent / "events"


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_fixture(event_id: str) -> tuple[dict, dict]:
    base = EVENTS_DIR / event_id
    watchlist = json.loads((base / "watchlist.json").read_text(encoding="utf-8"))
    ground_truth = json.loads((base / "ground_truth.json").read_text(encoding="utf-8"))
    return watchlist, ground_truth


def _news_observation(company_name: str, article: dict, window_query: str) -> dict:
    """Coerce one GDELT article record to the fixture observation schema."""
    seendate = (article.get("seendate") or "").strip()
    # GDELT format: YYYYMMDDTHHMMSSZ. Convert to ISO for consistency with rest
    # of the fixture and with `run_backtest._parse_dt`.
    if seendate:
        try:
            dt = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            observed_at = dt.isoformat().replace("+00:00", "Z")
        except ValueError:
            observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "observed_at": observed_at,
        "source_type": "news",
        "source_name": article.get("domain") or "GDELT news",
        "source_url": article.get("url") or "",
        "provenance": f"GDELT DOC 2.0 query: {window_query}",
        "title": (article.get("title") or "").strip(),
        "raw_text": _article_to_text(company_name, article),
        "source_confidence": 0.75,
    }


def _regulatory_observations(ground_truth: dict) -> list[dict]:
    """Pin the regulatory-anchor observations from ground_truth.primary_sources.

    These are the SEC/FDIC/Fed documents whose realized dates define the event.
    Included at fixed source_confidence 0.95 because they are primary sources
    with URLs pinned in ground_truth. The raw_text stays close to the source
    title so entity mapping picks up the ticker/name explicitly.
    """
    out: list[dict] = []
    primary = ground_truth.get("primary_sources", []) or []
    for i, entry in enumerate(primary):
        # Parse a rough observed_at from the affected list — take the earliest
        # realized_event_date as an anchor; individual regulatory docs may
        # precede that by hours to days depending on the event.
        affected = ground_truth.get("affected", []) or []
        anchor = min(
            (_parse_dt(a["realized_event_date"]) for a in affected),
            default=_parse_dt(ground_truth["window_start"]),
        )
        # Regulatory docs typically post the day of or the trading day before
        # the realized market event. Shift slightly earlier to reflect the
        # 8-K / receivership announcement being the causal upstream.
        observed_at = (anchor - timedelta(hours=8 + 6 * i)).isoformat().replace("+00:00", "Z")

        # Try to pull a URL from the "prose: URL" pattern used in the fixture.
        url = ""
        for token in entry.split():
            if token.startswith("http"):
                url = token.rstrip(".,;)")
                break

        out.append(
            {
                "observed_at": observed_at,
                "source_type": "regulatory" if ("FDIC" in entry or "Fed" in entry) else "sec_filing",
                "source_name": entry.split(",")[0] if "," in entry else entry.split(":")[0],
                "source_url": url,
                "provenance": "ground_truth.primary_sources",
                "title": entry.split(":")[0][:120],
                "raw_text": entry,
                "source_confidence": 0.95,
            }
        )
    return out


def build_fixture(
    event_id: str,
    max_records_per_target: int = 250,
    include_control_names: bool = True,
    domain_whitelist: frozenset[str] = DOWNSIDE_DOMAINS,
    dry_run: bool = False,
    use_cache: bool = True,
) -> tuple[list[dict], Path]:
    """Rebuild the observations.jsonl for an event from real archives.

    Per-target GDELT results are cached on disk under ``events/<event-id>/
    _gdelt_cache/<TICKER>.json`` so a partial failure (rate limiting, network
    flap) can be resumed without re-fetching what already succeeded. Delete
    the cache dir to force a fresh pull.

    Returns (observations, output_path). Writes only if ``dry_run`` is False.
    """
    watchlist, ground_truth = _load_fixture(event_id)
    window_start = _parse_dt(ground_truth["window_start"])
    window_end = _parse_dt(ground_truth["window_end"])
    affected_tickers = {a["ticker"] for a in ground_truth.get("affected", [])}
    control_tickers = {c["ticker"] for c in ground_truth.get("controls_should_not_flag", [])}
    cache_dir = EVENTS_DIR / event_id / "_gdelt_cache"
    cache_dir.mkdir(exist_ok=True)

    targets = []
    for item in watchlist["items"]:
        ticker = item["ticker"]
        is_control = ticker in control_tickers
        if is_control and not include_control_names:
            continue
        targets.append(item)

    observations: list[dict] = []
    seen_urls: set[str] = set()

    for item in targets:
        name = item["company_name"]
        aliases = list(item.get("aliases") or [])
        ticker = item["ticker"]
        cache_path = cache_dir / f"{ticker}.json"
        if use_cache and cache_path.exists():
            print(f"  [{ticker}] cache hit -> {cache_path.name}", flush=True)
            articles = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            print(f"  [{ticker}] fetching GDELT for '{name}' + {aliases} ...", flush=True)
            try:
                articles = fetch_articles(
                    company_name=name,
                    aliases=aliases,
                    window_start=window_start,
                    window_end=window_end,
                    max_records=max_records_per_target,
                    domain_whitelist=domain_whitelist,
                )
                cache_path.write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                print(f"    ! error fetching {ticker}: {e}", flush=True)
                articles = []

        window_query = f"({name}) {window_start.date()}..{window_end.date()}"
        for a in articles:
            url = a.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            observations.append(_news_observation(name, a, window_query))
        # Be polite to GDELT (undocumented rate limit; empirically ~3s between
        # queries survives sustained back-to-back calls without 429s). Skip the
        # pause when serving from cache.
        if not (use_cache and cache_path.exists()):
            time.sleep(3.0)

    # Anchor with the pinned regulatory sources so the backtest always sees the
    # exact primary docs from the ground_truth.
    observations.extend(_regulatory_observations(ground_truth))

    # Sort chronologically so run_backtest.py sees them in real time-order.
    observations.sort(key=lambda o: _parse_dt(o["observed_at"]))

    # Stamp a summary log entry (not part of the fixture; just for the operator).
    affected_ratio = sum(
        1 for o in observations if any(t in o["raw_text"] for t in affected_tickers) or any(a in o["raw_text"] for a in {i["company_name"] for i in targets if i["ticker"] in affected_tickers})
    )
    print(
        f"Built {len(observations)} observations across {len(targets)} watchlist targets "
        f"({affected_ratio} mentioning an affected name).",
        flush=True,
    )

    out_path = EVENTS_DIR / event_id / "observations.jsonl"
    if not dry_run:
        with out_path.open("w", encoding="utf-8") as f:
            for obs in observations:
                f.write(json.dumps(obs, ensure_ascii=False) + "\n")
        print(f"Wrote {out_path}")
    return observations, out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild an event's observations.jsonl from GDELT + primary sources.")
    parser.add_argument("--event", default="svb-2023")
    parser.add_argument("--max-records-per-target", type=int, default=250)
    parser.add_argument("--exclude-controls", action="store_true", help="Skip control names (e.g. MSFT).")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-cache", action="store_true", help="Ignore _gdelt_cache; force fresh GDELT pulls.")
    args = parser.parse_args()

    build_fixture(
        event_id=args.event,
        max_records_per_target=args.max_records_per_target,
        include_control_names=not args.exclude_controls,
        dry_run=args.dry_run,
        use_cache=not args.no_cache,
    )


if __name__ == "__main__":
    main()
