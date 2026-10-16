from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import get_db, operator_can_access_client, require_operator
from app.models.entities import BriefingRuns, Deliveries
from app.services.delivery.service import deliver_briefing, retry_failed_delivery

router = APIRouter(prefix="/delivery", tags=["delivery"], dependencies=[Depends(require_operator)])


class DeliveryRequest(BaseModel):
    recipient: EmailStr
    channel: str = "email"


@router.post("/briefings/{briefing_run_id}")
def deliver_briefing_endpoint(
    briefing_run_id: str,
    payload: DeliveryRequest,
    claims: dict = Depends(require_operator),
    db: Session = Depends(get_db),
):
    run = db.query(BriefingRuns).filter(BriefingRuns.id == briefing_run_id).one()
    # Sending a client's brief needs an admin, or an analyst assigned to that
    # client. Viewers never send. Authority comes from the token, never a header.
    if claims.get("role") not in {"admin", "analyst"} or not operator_can_access_client(db, claims, str(run.client_id)):
        raise HTTPException(status_code=403, detail="Delivery requires admin or an analyst assigned to this client")
    return deliver_briefing(db, briefing_run_id=briefing_run_id, recipient=payload.recipient, channel=payload.channel)


@router.get("/history")
def delivery_history_endpoint(limit: int = 100, status: str | None = None, channel: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Deliveries)
    if status:
        q = q.filter(Deliveries.delivery_status == status)
    if channel:
        q = q.filter(Deliveries.channel == channel)
    return q.order_by(Deliveries.created_at.desc()).limit(limit).all()


@router.post("/retry/{delivery_id}")
def retry_failed_delivery_endpoint(delivery_id: str, db: Session = Depends(get_db)):
    return retry_failed_delivery(db, delivery_id)
