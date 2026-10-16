"""Observation -> entities -> evidence -> signals, shared by the API and workers."""
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.entities import (
    CompanyAliases,
    Deliveries,
    SourceObservations,
    WatchlistItems,
    Watchlists,
)
from app.services.entity_mapping.service import extract_entities, map_to_watchlist, persist_entities
from app.services.ingestion.edgar_adapter import ingest_filings_for_ticker
from app.services.ingestion.gdelt_adapter import ingest_articles_for_target
from app.services.signals.service import signals_for_new_evidence
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


def process_observation(db: Session, observation: SourceObservations) -> dict:
    """Extract entities, map to watchlists and raise signals for shippable evidence."""
    persist_entities(db, observation.id, extract_entities(observation.raw_text))
    links = map_to_watchlist(db, observation)
    signals = signals_for_new_evidence(db, links)
    return {"evidence_links_created": len(links), "signals_created": len(signals)}


def _active_targets(db: Session) -> list[WatchlistItems]:
    """One active watchlist item per ticker across all active watchlists."""
    rows = (
        db.query(WatchlistItems)
        .join(Watchlists, Watchlists.id == WatchlistItems.watchlist_id)
        .filter(WatchlistItems.active.is_(True), Watchlists.active.is_(True))
        .all()
    )
    by_ticker: dict[str, WatchlistItems] = {}
    for row in rows:
        by_ticker.setdefault(row.ticker.upper(), row)
    return list(by_ticker.values())


def ingest_watchlist_sources(db: Session, lookback_hours: int = 24, edgar_limit: int = 10) -> dict:
    """Pull EDGAR filings and GDELT news for every active watchlist ticker.

    Each source failure is logged and skipped so one bad ticker or a GDELT
    outage does not abort the whole sweep. Dedupe keys make reruns idempotent.
    """
    window_end = utcnow()
    window_start = window_end - timedelta(hours=lookback_hours)
    totals = {"targets": 0, "observations": 0, "evidence_links_created": 0, "signals_created": 0, "errors": 0}
    aliases_by_ticker: dict[str, list[str]] = {}
    for a in db.query(CompanyAliases).all():
        if a.ticker:
            aliases_by_ticker.setdefault(a.ticker.upper(), []).append(a.alias)

    for item in _active_targets(db):
        totals["targets"] += 1
        new_obs: list[SourceObservations] = []
        try:
            new_obs.extend(ingest_filings_for_ticker(db, item.ticker, limit=edgar_limit))
        except Exception as exc:  # noqa: BLE001 - isolate per-source failures
            db.rollback()
            totals["errors"] += 1
            logger.warning("edgar ingestion failed", extra={"ticker": item.ticker, "error": str(exc)})
        try:
            new_obs.extend(
                ingest_articles_for_target(
                    db,
                    company_name=item.company_name,
                    window_start=window_start,
                    window_end=window_end,
                    aliases=aliases_by_ticker.get(item.ticker.upper()),
                )
            )
        except Exception as exc:  # noqa: BLE001 - isolate per-source failures
            db.rollback()
            totals["errors"] += 1
            logger.warning("gdelt ingestion failed", extra={"ticker": item.ticker, "error": str(exc)})
        for obs in new_obs:
            result = process_observation(db, obs)
            totals["observations"] += 1
            totals["evidence_links_created"] += result["evidence_links_created"]
            totals["signals_created"] += result["signals_created"]
    return totals


def dead_letter_exhausted_deliveries(db: Session, max_attempts: int = 3) -> int:
    """Move failed deliveries that exhausted their retries to ``dead_letter``.

    Keeps the retry sweep cheap and surfaces them in ops metrics for a human.
    """
    rows = (
        db.query(Deliveries)
        .filter(Deliveries.delivery_status == "failed", Deliveries.attempt_count >= max_attempts)
        .all()
    )
    for row in rows:
        row.delivery_status = "dead_letter"
    db.commit()
    return len(rows)


def archive_old_observations(db: Session, days: int = 180) -> int:
    """Mark observations older than ``days`` as archived/stale.

    Rows are kept, not deleted: evidence links, signals and briefings reference
    them, and the audit trail must stay reconstructable.
    """
    cutoff = utcnow() - timedelta(days=days)
    count = (
        db.query(SourceObservations)
        .filter(SourceObservations.observed_at < cutoff, SourceObservations.ingestion_status != "archived")
        .update({"ingestion_status": "archived", "stale": True}, synchronize_session=False)
    )
    db.commit()
    return count
