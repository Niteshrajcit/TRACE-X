from typing import Optional

from pydantic import BaseModel, EmailStr

from app.db.models.enums import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    jurisdiction_id: Optional[str] = None


class TokenClaims(BaseModel):
    """Shape of the decoded JWT (docs/API_CONTRACT.md §6)."""

    sub: str
    role: UserRole
    jurisdiction_id: Optional[str] = None
    bank_id: Optional[str] = None
