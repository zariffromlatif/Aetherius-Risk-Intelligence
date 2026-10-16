"""Did the first flag come before the market reacted, or with it?

For each detected name, find the earliest observation in the frozen corpus that
(a) maps to that name and (b) reports a price decline already underway
("shares plunge", "stock drops", "falling today", ...). Compare it with the
backtest's first shippable flag.

A flag at or after the first price-reaction headline is evidence of timely
*triage*, not of anticipating the market. The backtest's ``lead_time`` is
measured to the formal resolution date (receivership, insolvency, Chapter 11),
which is a different, later clock.

Usage:
    python simulations/backtest/market_reaction_check.py            # all events
    python simulations/backtest/market_reaction_check.py --markdown # table for the paper
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))

from run_backtest import _load_event, _parse_dt, run_backtest  # noqa: E402

from app.services.entity_mapping.service import match_item  # noqa: E402

EVENTS = ("svb-2023", "wirecard-2020", "ftx-2022")

# A price decline being reported: a price noun near a falling verb, or a
# "falling today"-style construction. Fixed before reading per-event results.
_PRICE_NOUN = r"(?:shares?|stocks?|equit(?:y|ies)|market value|selloff|sell-off)"
_FALL_VERB = r"(?:plunge[sd]?|plummet(?:s|ed)?|tumble[sd]?|sink[s]?|sank|slump(?:s|ed)?|drop(?:s|ped)?|fall(?:s|ing)?|fell|slide[s]?|slid|crash(?:es|ed)?|shudder|tank(?:s|ed)?)"
PRICE_REACTION_RE = re.compile(
    rf"\b{_PRICE_NOUN}\b.{{0,60}}\b{_FALL_VERB}\b|\b{_FALL_VERB}\b.{{0,40}}\b{_PRICE_NOUN}\b|\bare falling\b|\bselloff\b|\bsell-off\b",
    re.IGNORECASE,
)


def reports_price_reaction(text: str) -> bool:
    return bool(PRICE_REACTION_RE.search(text or ""))


def check_event(event_id: str) -> list[dict]:
    watchlist, observations, _ = _load_event(event_id)
    items = {i["ticker"]: i for i in watchlist["items"]}
    metrics = run_backtest(event_id, commit="market-reaction-check")
    rows = []
    for det in metrics["detections"]:
        item = items[det["ticker"]]
        first_reaction = None
        for obs in observations:  # already chronological
            text = obs.get("title") or obs.get("raw_text", "")
            if not reports_price_reaction(text):
                continue
            if match_item(
                obs["raw_text"].upper(),
                ticker=item["ticker"],
                company_name=item.get("company_name"),
                sector=item.get("sector"),
                aliases=item.get("aliases"),
                relationships=item.get("relationships"),
            ):
                first_reaction = obs
                break
        flag_dt = _parse_dt(det["first_flag_at"])
        react_dt = _parse_dt(first_reaction["observed_at"]) if first_reaction else None
        lead_over_reaction_h = (react_dt - flag_dt).total_seconds() / 3600 if react_dt else None
        rows.append(
            {
                "event_id": event_id,
                "ticker": det["ticker"],
                "first_flag_at": det["first_flag_at"],
                "first_flag_reports_price_move": reports_price_reaction(det["evidence_title"] or ""),
                "first_price_reaction_at": first_reaction["observed_at"] if first_reaction else None,
                "flag_lead_over_reaction_hours": round(lead_over_reaction_h, 1) if react_dt else None,
                "lead_to_resolution_days": det["lead_time_days"],
                "evidence_title": det["evidence_title"],
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    rows = [r for e in EVENTS for r in check_event(e)]
    if args.markdown:
        print("| Event | Ticker | First flag | First price-reaction headline | Flag lead over reaction (h) | Flag headline itself reports a fall | Lead to resolution (d) |")
        print("|---|---|---|---|---|---|---|")
        for r in rows:
            lead = "n/a" if r["flag_lead_over_reaction_hours"] is None else f"{r['flag_lead_over_reaction_hours']:+.1f}"
            print(f"| {r['event_id']} | {r['ticker']} | {r['first_flag_at']} | {r['first_price_reaction_at'] or 'none in corpus'} | {lead} | {'yes' if r['first_flag_reports_price_move'] else 'no'} | {r['lead_to_resolution_days']} |")
    else:
        for r in rows:
            print(r)
    ahead = [r for r in rows if (r["flag_lead_over_reaction_hours"] or 0) > 0]
    same = sum(1 for r in rows if r["first_flag_reports_price_move"])
    print(f"\n{len(rows)} detections; first flag itself reports a price fall in {same}; "
          f"flag strictly precedes the first price-reaction headline in {len(ahead)}.")


if __name__ == "__main__":
    main()
