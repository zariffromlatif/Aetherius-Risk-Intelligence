from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_operator
from app.models.entities import SourceObservations
from app.services.ingestion.service import ingest_observation
from app.services.pipeline.service import process_observation

router = APIRouter(prefix="/observations", tags=["observations"], dependencies=[Depends(require_operator)])


class ObservationCreate(BaseModel):
    source_type: str
    source_name: str
    source_url: str | None = None
    title: str | None = None
    raw_text: str
    observed_at: datetime | None = None
    source_confidence: float = 0.7
    dedupe_key: str | None = None


@router.post("")
def create_observation_endpoint(payload: ObservationCreate, db: Session = Depends(get_db)):
    observation = ingest_observation(
        db=db,
        source_type=payload.source_type,
        source_name=payload.source_name,
        source_url=payload.source_url,
        title=payload.title,
        raw_text=payload.raw_text,
        observed_at=payload.observed_at or datetime.now(timezone.utc),
        source_confidence=payload.source_confidence,
        dedupe_key=payload.dedupe_key,
    )
    if observation is None:
        return {"deduped": True}
    result = process_observation(db, observation)
    return {"deduped": False, "observation_id": str(observation.id), **result}


@router.get("")
def list_observations_endpoint(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(SourceObservations).order_by(SourceObservations.ingested_at.desc()).limit(limit).all()
    return rows
