
from sqlalchemy.orm import Session

from app.models.entities import BriefingRuns, OperatorActions
from app.utils.time import utcnow


def set_review_action(
    db: Session,
    briefing_run_id: str,
    action_type: str,
    operator_user_id: str | None = None,
    reason: str | None = None,
    before_payload: dict | None = None,
    after_payload: dict | None = None,
) -> BriefingRuns:
    run = db.query(BriefingRuns).filter(BriefingRuns.id == briefing_run_id).one()
    if action_type == "approve":
        run.status = "approved"
        run.approved_at = utcnow()
    elif action_type == "suppress":
        run.status = "suppressed"
    elif action_type == "resend":
        # A resend re-triggers delivery of an already-finalized run; it must not
        # rewind the run's status (e.g. "sent" -> "approved"), which would make
        # the brief reappear in the review queue as if unapproved. The resend is
        # captured in OperatorActions below for the audit trail.
        pass
    elif action_type == "edit":
        run.version = run.version + 1
    else:
        raise ValueError("Unsupported action")

    db.add(
        OperatorActions(
            briefing_run_id=briefing_run_id,
            action_type=action_type,
            operator_user_id=operator_user_id,
            before_payload=before_payload,
            after_payload=after_payload,
            reason=reason,
        )
    )
    db.commit()
    db.refresh(run)
    return run
