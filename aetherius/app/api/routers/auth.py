from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models.entities import Clients, OperatorClientAssignments, OperatorUsers
from app.schemas.auth import (
    ClientAssignmentCreate,
    ClientAssignmentOut,
    LoginRequest,
    OperatorCreate,
    OperatorOut,
    TokenResponse,
)
from app.services.auth.service import authenticate_operator, create_access_token, create_operator

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_operator(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(user))


@router.post("/operators", response_model=OperatorOut, dependencies=[Depends(require_admin)])
def create_operator_endpoint(payload: OperatorCreate, db: Session = Depends(get_db)):
    return create_operator(db, email=payload.email, password=payload.password, role=payload.role, full_name=payload.full_name)


@router.post("/bootstrap-admin", response_model=OperatorOut)
def bootstrap_admin(payload: OperatorCreate, db: Session = Depends(get_db)):
    existing = db.query(OperatorUsers).count()
    if existing > 0:
        raise HTTPException(status_code=403, detail="Bootstrap disabled after first operator exists")
    return create_operator(db, email=payload.email, password=payload.password, role="admin", full_name=payload.full_name)


@router.post("/assignments", response_model=ClientAssignmentOut, dependencies=[Depends(require_admin)])
def create_assignment_endpoint(payload: ClientAssignmentCreate, db: Session = Depends(get_db)):
    if not db.query(OperatorUsers).filter(OperatorUsers.id == payload.operator_user_id).first():
        raise HTTPException(status_code=404, detail="Operator not found")
    if not db.query(Clients).filter(Clients.id == payload.client_id).first():
        raise HTTPException(status_code=404, detail="Client not found")
    existing = (
        db.query(OperatorClientAssignments)
        .filter(
            OperatorClientAssignments.operator_user_id == payload.operator_user_id,
            OperatorClientAssignments.client_id == payload.client_id,
        )
        .first()
    )
    if existing:
        return existing
    row = OperatorClientAssignments(operator_user_id=payload.operator_user_id, client_id=payload.client_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/assignments/{assignment_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_assignment_endpoint(assignment_id: str, db: Session = Depends(get_db)):
    row = db.query(OperatorClientAssignments).filter(OperatorClientAssignments.id == assignment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(row)
    db.commit()
