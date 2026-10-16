import json
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.deps import operator_can_access_client
from app.services.delivery.service import DUPLICATE_SUPPRESSED, retry_backoff, retry_failed_delivery

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = REPO_ROOT / "simulations" / "backtest"
if str(BACKTEST_DIR) not in sys.path:
    sys.path.append(str(BACKTEST_DIR))


def _db_returning(row) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.one.return_value = row
    db.query.return_value.filter.return_value.first.return_value = row
    return db


def test_retry_backoff_doubles() -> None:
    assert retry_backoff(1) == timedelta(minutes=5)
    assert retry_backoff(2) == timedelta(minutes=10)
    assert retry_backoff(3) == timedelta(minutes=20)


@pytest.mark.parametrize(
    "delivery",
    [
        SimpleNamespace(delivery_status="sent", attempt_count=1, error_message=None, last_attempt_at=None),
        SimpleNamespace(delivery_status="failed", attempt_count=3, error_message="smtp down", last_attempt_at=None),
        SimpleNamespace(delivery_status="failed", attempt_count=1, error_message=DUPLICATE_SUPPRESSED, last_attempt_at=None),
    ],
)
def test_retry_skips_non_retryable(delivery, monkeypatch) -> None:
    called = []
    monkeypatch.setattr("app.services.delivery.service._attempt_delivery", lambda db, d: called.append(d) or d)
    assert retry_failed_delivery(_db_returning(delivery), "x") is delivery
    assert not called


def test_retry_respects_backoff_window(monkeypatch) -> None:
    from app.utils.time import utcnow

    delivery = SimpleNamespace(delivery_status="failed", attempt_count=1, error_message="smtp down", last_attempt_at=utcnow())
    called = []
    monkeypatch.setattr("app.services.delivery.service._attempt_delivery", lambda db, d: called.append(d) or d)
    retry_failed_delivery(_db_returning(delivery), "x", respect_backoff=True)
    assert not called
    retry_failed_delivery(_db_returning(delivery), "x", respect_backoff=False)
    assert called == [delivery]


def test_admin_can_access_any_client() -> None:
    db = MagicMock()
    assert operator_can_access_client(db, {"role": "admin", "sub": str(uuid.uuid4())}, str(uuid.uuid4()))
    db.query.assert_not_called()


def test_analyst_needs_assignment() -> None:
    claims = {"role": "analyst", "sub": str(uuid.uuid4())}
    assert not operator_can_access_client(_db_returning(None), claims, str(uuid.uuid4()))
    assert operator_can_access_client(_db_returning(object()), claims, str(uuid.uuid4()))


@pytest.mark.parametrize(
    ("claims", "client_id"),
    [({"role": "analyst"}, str(uuid.uuid4())), ({"role": "analyst", "sub": "nope"}, str(uuid.uuid4())), ({"role": "analyst", "sub": str(uuid.uuid4())}, "bad")],
)
def test_malformed_ids_are_denied(claims, client_id) -> None:
    assert not operator_can_access_client(_db_returning(object()), claims, client_id)


def test_backtest_keeps_commit_label_when_numbers_unchanged(tmp_path) -> None:
    mod = pytest.importorskip("run_backtest")
    metrics = {"commit": "fresh", "detection_recall": 1.0}
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"commit": "pinned-label", "detection_recall": 1.0}), encoding="utf-8")
    assert mod._resolve_commit(metrics, path, None) == "pinned-label"
    assert mod._resolve_commit(metrics, path, "explicit") == "explicit"
    path.write_text(json.dumps({"commit": "pinned-label", "detection_recall": 0.5}), encoding="utf-8")
    assert mod._resolve_commit(metrics, path, None) != "pinned-label"
