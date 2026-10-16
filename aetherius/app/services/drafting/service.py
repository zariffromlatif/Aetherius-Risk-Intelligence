
from sqlalchemy.orm import Session

from app.models.entities import BriefingEvidenceRefs, BriefingItems, BriefingRuns, RiskSignals
from app.utils.time import utcnow


def create_briefing_run(db: Session, client_id: str, run_type: str, status: str = "draft") -> BriefingRuns:
    run = BriefingRuns(client_id=client_id, run_type=run_type, status=status, generated_at=utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def draft_daily_brief(db: Session, client_id: str) -> BriefingRuns:
    run = create_briefing_run(db, client_id, "daily_brief", "pending_review")
    signals = (
        db.query(RiskSignals)
        .filter(RiskSignals.client_id == client_id, RiskSignals.status == "open")
        .order_by(RiskSignals.brief_priority_score.desc())
        .limit(5)
        .all()
    )
    if not signals:
        item = BriefingItems(
            briefing_run_id=run.id,
            section_type="executive_summary",
            display_order=1,
            title="No Material Change",
            body="No new high-confidence downside signals detected in the current window.",
        )
        db.add(item)
        db.commit()
        return run

    summary = BriefingItems(
        briefing_run_id=run.id,
        section_type="executive_summary",
        display_order=0,
        title="Executive Summary",
        body="Prioritized downside watchlist signals for operator review.",
    )
    db.add(summary)
    db.commit()

    for idx, s in enumerate(signals[:5], start=1):
        bi = BriefingItems(
            briefing_run_id=run.id,
            watchlist_item_id=s.watchlist_item_id,
            section_type="priority_flag",
            display_order=idx,
            title=s.headline,
            body=f"{s.why_it_matters}\nPathway: {s.pathway}\nWatch next: {s.watch_next}",
            severity_level=s.severity_level,
            confidence_level=s.confidence_level,
        )
        db.add(bi)
        db.commit()
        db.refresh(bi)
        db.add(BriefingEvidenceRefs(briefing_item_id=bi.id, risk_signal_id=s.id, rank_order=1))
        db.commit()
    return run


def draft_urgent_alerts(db: Session, client_id: str, threshold: float = 0.75) -> list[BriefingRuns]:
    signals = (
        db.query(RiskSignals)
        .filter(RiskSignals.client_id == client_id, RiskSignals.status == "open", RiskSignals.urgency_score >= threshold)
        .order_by(RiskSignals.urgency_score.desc())
        .all()
    )
    runs: list[BriefingRuns] = []
    for s in signals:
        run = create_briefing_run(db, client_id, "urgent_alert", "pending_review")
        bi = BriefingItems(
            briefing_run_id=run.id,
            watchlist_item_id=s.watchlist_item_id,
            section_type="priority_flag",
            display_order=1,
            title=s.headline,
            body=f"{s.why_it_matters}\nWatch next: {s.watch_next}",
            severity_level=s.severity_level,
            confidence_level=s.confidence_level,
        )
        db.add(bi)
        db.commit()
        db.refresh(bi)
        db.add(BriefingEvidenceRefs(briefing_item_id=bi.id, risk_signal_id=s.id, rank_order=1))
        db.commit()
        runs.append(run)
    return runs


def draft_weekly_summary(db: Session, client_id: str) -> BriefingRuns:
    """Draft a weekly summary run for operator review from reporting counts."""
    from app.services.reporting.service import build_weekly_summary

    summary = build_weekly_summary(db, client_id)
    run = create_briefing_run(db, client_id, "weekly_summary", "pending_review")
    db.add(
        BriefingItems(
            briefing_run_id=run.id,
            section_type="executive_summary",
            display_order=0,
            title="Weekly Summary",
            body=(
                f"Daily briefs sent: {summary['sent_daily_briefs']}. "
                f"Open downside signals: {summary['open_signals']}."
            ),
        )
    )
    db.commit()
    return run
