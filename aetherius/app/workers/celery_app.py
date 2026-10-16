from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "aetherius",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.task_track_started = True
celery_app.conf.task_default_retry_delay = 30
celery_app.conf.task_routes = {
    "app.workers.tasks.ingest_*": {"queue": "ingestion"},
    "app.workers.tasks.signal_*": {"queue": "signal"},
    "app.workers.tasks.briefing_*": {"queue": "briefing"},
    "app.workers.tasks.delivery_*": {"queue": "delivery"},
}
celery_app.conf.beat_schedule = {
    "watchlist-ingestion-job": {
        "task": "app.workers.tasks.ingest_watchlist_sources",
        "schedule": crontab(minute=5),
    },
    "daily-brief-job": {
        "task": "app.workers.tasks.briefing_daily_sweep",
        "schedule": crontab(minute=0, hour=8),
    },
    "weekly-summary-job": {
        "task": "app.workers.tasks.briefing_weekly_sweep",
        "schedule": crontab(minute=0, hour=9, day_of_week="mon"),
    },
    "delivery-retry-job": {
        "task": "app.workers.tasks.delivery_retry_failed",
        "schedule": crontab(minute="*/5"),
    },
    "health-alerts-job": {
        "task": "app.workers.tasks.observability_health_alerts",
        "schedule": crontab(minute="*/10"),
    },
    "dead-letter-job": {
        "task": "app.workers.tasks.dead_letter_requeue",
        "schedule": crontab(minute="*/15"),
    },
    "retention-job": {
        "task": "app.workers.tasks.retention_archive_cleanup",
        "schedule": crontab(minute=0, hour=2),
    },
}
