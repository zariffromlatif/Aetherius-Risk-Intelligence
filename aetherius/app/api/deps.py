import uuid

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.entities import OperatorClientAssignments


def db_dep() -> Session:
    return Depends(get_db)


def _decode_bearer(authorization: str) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}") from exc


def require_operator(authorization: str = Header(default="")) -> dict:
    return _decode_bearer(authorization)


def require_admin(claims: dict = Depends(require_operator)) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return claims


def operator_can_access_client(db: Session, claims: dict, client_id: str) -> bool:
    """Admins may act on every client; others only on clients assigned to them."""
    if claims.get("role") == "admin":
        return True
    operator_id = claims.get("sub")
    if not operator_id:
        return False
    try:
        operator_uuid = uuid.UUID(str(operator_id))
        client_uuid = uuid.UUID(str(client_id))
    except ValueError:
        return False
    return (
        db.query(OperatorClientAssignments)
        .filter(
            OperatorClientAssignments.operator_user_id == operator_uuid,
            OperatorClientAssignments.client_id == client_uuid,
        )
        .first()
        is not None
    )


def require_client_scope(
    client_id: str,
    claims: dict = Depends(require_operator),
    db: Session = Depends(get_db),
) -> dict:
    # Authority is derived from the authenticated operator and the
    # operator_client_assignments table, never from a client-supplied header.
    if operator_can_access_client(db, claims, client_id):
        return claims
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Operator is not assigned to this client",
    )
