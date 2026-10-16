from celery.utils.log import get_task_logger
from sqlalchemy import func

from app.db.session import SessionLocal
from app.models.entities import BriefingRuns, Clients, Deliveries, SourceObservations
from app.services.delivery.service import retry_failed_deliveries
from app.services.drafting.service import draft_daily_brief, draft_weekly_summary
from app.services.pipeline.service import (
    archive_old_observations,
    dead_letter_exhausted_deliveries,
    ingest_watchlist_sources,
)
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)

# Thresholds for observability_health_alerts.
FAILED_DELIVERY_ALERT_THRESHOLD = 5
DEAD_LETTER_ALERT_THRESHOLD = 1
PENDING_REVIEW_ALERT_THRESHOLD = 25


@celery_app.task(bind=True, max_retries=3, name="app.workers.tasks.ingest_watchlist_sources")
def ingest_watchlist_sources_task(self, lookback_hours: int = 24):
    db = SessionLocal()
    try:
        totals = ingest_watchlist_sources(db, lookback_hours=lookback_hours)
        logger.info("watchlist ingestion complete", extra={**totals, "task_id": self.request.id})
        return totals
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, name="app.workers.tasks.briefing_daily_sweep")
def briefing_daily_sweep(self):
    db = SessionLocal()
    try:
        for client in db.query(Clients).all():
            draft_daily_brief(db, str(client.id))
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, name="app.workers.tasks.briefing_weekly_sweep")
def briefing_weekly_sweep(self):
    db = SessionLocal()
    try:
        clients = db.query(Clients).all()
        for client in clients:
            draft_weekly_summary(db, str(client.id))
        logger.info("weekly sweep complete", extra={"clients": len(clients), "task_id": self.request.id})
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, name="app.workers.tasks.delivery_retry_failed")
def delivery_retry_failed(self):
    db = SessionLocal()
    try:
        results = retry_failed_deliveries(db)
        sent = sum(1 for d in results if d.delivery_status == "sent")
        logger.info("delivery retry sweep complete", extra={"attempted": len(results), "sent": sent, "task_id": self.request.id})
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, name="app.workers.tasks.observability_health_alerts")
def observability_health_alerts(self):
    db = SessionLocal()
    try:
        failed = db.query(func.count(Deliveries.id)).filter(Deliveries.delivery_status == "failed").scalar() or 0
        dead = db.query(func.count(Deliveries.id)).filter(Deliveries.delivery_status == "dead_letter").scalar() or 0
        pending = (
            db.query(func.count(BriefingRuns.id)).filter(BriefingRuns.status == "pending_review").scalar() or 0
        )
        stale = db.query(func.count(SourceObservations.id)).filter(SourceObservations.stale.is_(True)).scalar() or 0
        metrics = {"failed_deliveries": failed, "dead_letter_deliveries": dead, "pending_reviews": pending, "stale_observations": stale}
        alerts = []
        if failed >= FAILED_DELIVERY_ALERT_THRESHOLD:
            alerts.append("failed_deliveries")
        if dead >= DEAD_LETTER_ALERT_THRESHOLD:
            alerts.append("dead_letter_deliveries")
        if pending >= PENDING_REVIEW_ALERT_THRESHOLD:
            alerts.append("pending_reviews")
        if alerts:
            logger.warning("health alert", extra={**metrics, "alerts": alerts, "task_id": self.request.id})
        else:
            logger.info("health check ok", extra={**metrics, "task_id": self.request.id})
        return {**metrics, "alerts": alerts}
    finally:
        db.close()


@celery_app.task(bind=True, name="app.workers.tasks.dead_letter_requeue")
def dead_letter_requeue(self):
    db = SessionLocal()
    try:
        moved = dead_letter_exhausted_deliveries(db)
        logger.info("dead-letter sweep complete", extra={"moved": moved, "task_id": self.request.id})
        return moved
    finally:
        db.close()


@celery_app.task(bind=True, name="app.workers.tasks.retention_archive_cleanup")
def retention_archive_cleanup(self, days: int = 180):
    db = SessionLocal()
    try:
        archived = archive_old_observations(db, days=days)
        logger.info("retention cleanup complete", extra={"days": days, "archived": archived, "task_id": self.request.id})
        return archived
    finally:
        db.close()
