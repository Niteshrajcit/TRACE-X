from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.schemas import LoginRequest, LoginResponse
from app.core.security import create_access_token, verify_password
from app.db.models.users import User
from app.db.session import get_db

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.email == request.email.lower()).first()
    if user is None or not user.is_active or not verify_password(request.password, user.password_hash):
        # Same error for "no such user" and "wrong password" - do not leak
        # which one it was.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    token = create_access_token(
        {
            "sub": user.user_id,
            "role": user.role.value,
            "jurisdiction_id": user.jurisdiction_id,
            "bank_id": user.bank_id,
        }
    )
    return LoginResponse(
        access_token=token, role=user.role, jurisdiction_id=user.jurisdiction_id
    )
