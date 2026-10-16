"""Pins the paper's market-timing finding (simulations/backtest/market_reaction_check.py)."""

import sys
from pathlib import Path

import pytest

BACKTEST_DIR = Path(__file__).resolve().parents[2] / "simulations" / "backtest"
if str(BACKTEST_DIR) not in sys.path:
    sys.path.append(str(BACKTEST_DIR))

mrc = pytest.importorskip("market_reaction_check")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SVB Financial stock plummets toward biggest one-day selloff", True),
        ("Why Shares of First Republic Bank Are Falling Today", True),
        ("Wirecard shares plunge as Ernst & Young says no evidence", True),
        ("Signature Bank stock drops sharply after Silvergate winddown", True),
        ("Robinhood, Coinbase Distance Themselves from FTX After Crypto Plunge", False),
        ("Microsoft expands Copilot across product suite", False),
        ("Bank reports quarterly results", False),
    ],
)
def test_price_reaction_classifier(text: str, expected: bool) -> None:
    assert mrc.reports_price_reaction(text) is expected


def test_no_first_flag_precedes_the_market_reaction() -> None:
    rows = [r for e in mrc.EVENTS for r in mrc.check_event(e)]
    assert len(rows) == 9
    assert sum(1 for r in rows if r["first_flag_reports_price_move"]) == 8
    assert sum(1 for r in rows if (r["flag_lead_over_reaction_hours"] or 0) > 0) == 0
