from uuid import UUID

from pydantic import BaseModel, EmailStr


class OperatorCreate(BaseModel):
    email: EmailStr
    full_name: str | None = None
    password: str
    role: str = "viewer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OperatorOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str | None
    role: str
    active: bool

    class Config:
        from_attributes = True


class ClientAssignmentCreate(BaseModel):
    operator_user_id: UUID
    client_id: UUID


class ClientAssignmentOut(BaseModel):
    id: UUID
    operator_user_id: UUID
    client_id: UUID

    class Config:
        from_attributes = True
