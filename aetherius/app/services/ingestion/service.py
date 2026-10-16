import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.entities import SourceObservations
from app.utils.time import utcnow


def make_content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def compute_freshness(observed_at: datetime) -> float:
    # Tolerate naive datetimes by assuming UTC, so a single naive caller cannot
    # raise "can't subtract offset-naive and offset-aware datetimes".
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    age_hours = max((datetime.now(timezone.utc) - observed_at).total_seconds() / 3600, 0.0)
    return max(0.0, min(1.0, 1.0 - (age_hours / 72.0)))


def dedupe_observation(db: Session, content_hash: str, dedupe_key: str | None) -> bool:
    by_hash = db.query(SourceObservations).filter(SourceObservations.content_hash == content_hash).first()
    if by_hash:
        return True
    if dedupe_key:
        by_key = db.query(SourceObservations).filter(SourceObservations.dedupe_key == dedupe_key).first()
        if by_key:
            return True
    return False


def ingest_observation(
    db: Session,
    source_type: str,
    source_name: str,
    raw_text: str,
    observed_at: datetime,
    source_url: str | None = None,
    title: str | None = None,
    structured_payload: dict | None = None,
    source_confidence: float | None = 0.7,
    dedupe_key: str | None = None,
) -> SourceObservations | None:
    content_hash = make_content_hash(raw_text)
    if dedupe_observation(db, content_hash, dedupe_key):
        return None
    freshness = compute_freshness(observed_at)
    obj = SourceObservations(
        source_type=source_type,
        source_name=source_name,
        source_url=source_url,
        observed_at=observed_at,
        ingested_at=utcnow(),
        content_hash=content_hash,
        title=title,
        raw_text=raw_text,
        structured_payload=structured_payload,
        source_confidence=source_confidence,
        freshness_score=freshness,
        dedupe_key=dedupe_key,
        ingestion_status="stale" if freshness < 0.35 else "ingested",
        stale=freshness < 0.35,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
