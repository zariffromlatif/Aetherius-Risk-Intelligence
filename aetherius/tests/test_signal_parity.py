"""Live signal scoring must agree with the backtest harness on the same text."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.entity_mapping.service import match_item
from app.services.scoring.service import infer_signal_type
from app.services.signals.service import is_shippable, score_evidence

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = REPO_ROOT / "simulations" / "backtest"
if str(BACKTEST_DIR) not in sys.path:
    sys.path.append(str(BACKTEST_DIR))

run_backtest_mod = pytest.importorskip("run_backtest")


def _item(priority: str = "high") -> SimpleNamespace:
    return SimpleNamespace(priority_level=priority)


def _obs(text: str, source_confidence: float | None = 0.7, freshness: float | None = 0.9) -> SimpleNamespace:
    return SimpleNamespace(raw_text=text, source_confidence=source_confidence, freshness_score=freshness)


@pytest.mark.parametrize("event_id", ["svb-2023", "wirecard-2020", "ftx-2022"])
def test_live_scoring_matches_backtest_on_fixtures(event_id: str) -> None:
    base = BACKTEST_DIR / "events" / event_id
    watchlist = json.loads((base / "watchlist.json").read_text(encoding="utf-8"))
    rows = [json.loads(x) for x in (base / "observations.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    compared = 0
    for obs in rows:
        for item in watchlist["items"]:
            match = match_item(
                obs["raw_text"].upper(),
                ticker=item["ticker"],
                company_name=item.get("company_name"),
                sector=item.get("sector"),
                aliases=item.get("aliases"),
                relationships=item.get("relationships"),
            )
            if not match:
                continue
            rel, relevance = match
            expected = run_backtest_mod._score_observation(obs, item, rel, relevance)
            live = score_evidence(
                _obs(obs["raw_text"], float(obs.get("source_confidence", 0.7)), 0.9),
                _item(item.get("priority_level", "normal")),
                relevance,
            )
            assert live["risk_score"] == pytest.approx(expected["risk_score"])
            expected_ship = expected["severity"] in {"elevated", "high"} and expected["event_severity_score"] > 0.0
            assert is_shippable(live) == expected_ship
            compared += 1
    assert compared > 0


def test_benign_direct_mention_is_never_shippable() -> None:
    scored = score_evidence(_obs("Microsoft expands Copilot across product suite", 0.95, 1.0), _item("critical"), 0.9)
    assert scored["event_severity_score"] == 0.0
    assert scored["severity"] not in {"elevated", "high"}
    assert not is_shippable(scored)


def test_missing_observation_scores_fall_back_to_defaults() -> None:
    scored = score_evidence(_obs("deposit outflows and liquidity stress", None, None), _item(), 0.9)
    assert is_shippable(scored)


@pytest.mark.parametrize(
    ("rel", "text", "expected"),
    [
        ("direct", "Depositors pulled funds amid a liquidity squeeze", "liquidity_or_refinancing_risk"),
        ("direct", "Regulators open investigation into accounting fraud", "regulatory_risk"),
        ("direct", "Bank books unrealized loss on bond portfolio", "balance_sheet_stress"),
        ("direct", "Analysts downgraded the stock", "valuation_compression"),
        ("direct", "Company cuts full-year guidance", "guidance_risk"),
        ("direct", "Quarterly results announced", "earnings_risk"),
        ("sector", "Regional banks under pressure", "sector_contagion"),
        ("supplier_readthrough", "Supplier halts shipments", "supplier_readthrough"),
        ("peer_readthrough", "Fears of contagion spread", "sector_contagion"),
        ("peer_readthrough", "Peer reports quarter", "macro_spillover"),
    ],
)
def test_infer_signal_type_uses_content(rel: str, text: str, expected: str) -> None:
    assert infer_signal_type(rel, text) == expected
