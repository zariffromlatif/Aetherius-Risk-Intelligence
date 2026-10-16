"""Live accuracy ledger for shipped signals.

For every brief the pilot ships, operators and clients tag outcomes in the
``client_feedback`` table (e.g. ``useful`` / ``noisy`` / ``too_late``). This
script rolls those tags into a persistent CSV ledger
(``simulations/validation/accuracy_ledger.csv``) and prints a rolling
usefulness summary.

This is the "track record as a byproduct of getting paid" mechanism, using
the ground-truth policy in docs/benchmark_spec.md s5 (operator + client
feedback labels).

Runs against the live database via the backend's SessionLocal. If the backend
or DB is unavailable it exits cleanly with a message instead of crashing.

Usage:
    python simulations/backtest/grade_live_signals.py
    python simulations/backtest/grade_live_signals.py --out simulations/validation/accuracy_ledger.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "aetherius"
DEFAULT_LEDGER = REPO_ROOT / "simulations" / "validation" / "accuracy_ledger.csv"

FIELDNAMES = [
    "feedback_id",
    "recorded_at",
    "client_id",
    "briefing_run_id",
    "run_type",
    "feedback_type",
    "feedback_text",
    "recorded_by",
]

# Feedback tags that count as a "good" outcome when computing usefulness rate.
GOOD_TAGS = {"useful", "actioned", "accurate"}
BAD_TAGS = {"noisy", "too_late", "wrong", "not_actionable", "false_positive"}


def _load_existing_ids(ledger_path: Path) -> set[str]:
    if not ledger_path.exists():
        return set()
    with ledger_path.open(newline="", encoding="utf-8") as fh:
        return {row["feedback_id"] for row in csv.DictReader(fh)}


def collect_feedback_rows() -> list[dict] | None:
    """Return feedback rows joined to their briefing run, or None if DB unavailable."""
    if str(APP_ROOT) not in sys.path:
        sys.path.append(str(APP_ROOT))
    try:
        from app.db.session import SessionLocal  # type: ignore
        from app.models.entities import BriefingRuns, ClientFeedback  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"[grade_live_signals] backend/DB not importable ({exc}); nothing to grade.")
        return None

    db = SessionLocal()
    try:
        rows: list[dict] = []
        query = (
            db.query(ClientFeedback, BriefingRuns.run_type)
            .outerjoin(BriefingRuns, BriefingRuns.id == ClientFeedback.briefing_run_id)
            .order_by(ClientFeedback.created_at.asc())
        )
        for fb, run_type in query.all():
            rows.append(
                {
                    "feedback_id": str(fb.id),
                    "recorded_at": fb.created_at.isoformat() if fb.created_at else "",
                    "client_id": str(fb.client_id),
                    "briefing_run_id": str(fb.briefing_run_id) if fb.briefing_run_id else "",
                    "run_type": run_type or "",
                    "feedback_type": fb.feedback_type or "",
                    "feedback_text": (fb.feedback_text or "").replace("\n", " ").strip(),
                    "recorded_by": fb.recorded_by or "",
                }
            )
        return rows
    except Exception as exc:  # noqa: BLE001
        print(f"[grade_live_signals] query failed ({exc}); nothing to grade.")
        return None
    finally:
        db.close()


def append_new_rows(ledger_path: Path, rows: list[dict]) -> int:
    existing = _load_existing_ids(ledger_path)
    new_rows = [r for r in rows if r["feedback_id"] not in existing]
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not ledger_path.exists()
    with ledger_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        for r in new_rows:
            writer.writerow(r)
    return len(new_rows)


def summarize(ledger_path: Path) -> dict:
    if not ledger_path.exists():
        return {"total": 0, "good": 0, "bad": 0, "usefulness_rate": None}
    good = bad = total = 0
    with ledger_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            total += 1
            tag = row["feedback_type"].lower()
            if tag in GOOD_TAGS:
                good += 1
            elif tag in BAD_TAGS:
                bad += 1
    graded = good + bad
    return {
        "total": total,
        "good": good,
        "bad": bad,
        "usefulness_rate": round(good / graded, 3) if graded else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Roll client/operator feedback into the accuracy ledger.")
    parser.add_argument("--out", default=str(DEFAULT_LEDGER), help="Ledger CSV path.")
    args = parser.parse_args()
    ledger_path = Path(args.out)

    rows = collect_feedback_rows()
    if rows is not None:
        added = append_new_rows(ledger_path, rows)
        print(f"[grade_live_signals] appended {added} new feedback row(s) to {ledger_path}")

    stats = summarize(ledger_path)
    print(
        f"[grade_live_signals] ledger total={stats['total']} "
        f"good={stats['good']} bad={stats['bad']} "
        f"usefulness_rate={stats['usefulness_rate']}"
    )
    print("Note: usefulness rate is operator/client-adjudicated, not a return metric (benchmark_spec.md s10).")


if __name__ == "__main__":
    main()
