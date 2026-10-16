from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_operator
from app.models.entities import BriefingRuns, Deliveries, SourceObservations

router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(require_operator)])


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    return {
        "failed_deliveries": db.query(func.count(Deliveries.id)).filter(Deliveries.delivery_status == "failed").scalar() or 0,
        "dead_letter_deliveries": db.query(func.count(Deliveries.id)).filter(Deliveries.delivery_status == "dead_letter").scalar() or 0,
        "pending_reviews": db.query(func.count(BriefingRuns.id)).filter(BriefingRuns.status == "pending_review").scalar() or 0,
        "stale_observations": db.query(func.count(SourceObservations.id)).filter(SourceObservations.stale.is_(True)).scalar() or 0,
    }
