"""
FastAPI dependencies enforcing docs/SECURITY_AND_GOVERNANCE.md §3's RBAC
matrix. Authorization is derived entirely from the verified JWT claims -
the client never supplies jurisdiction_id as a trusted filter
(docs/API_CONTRACT.md §6).
"""
from typing import Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.schemas import TokenClaims
from app.core.security import decode_access_token
from app.db.models.enums import UserRole

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_claims(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> TokenClaims:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )
    try:
        return TokenClaims(**payload)
    except Exception as exc:  # malformed claims -> treat as unauthenticated
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token claims"
        ) from exc


def require_roles(*roles: UserRole):
    allowed: Iterable[UserRole] = roles

    def _check(claims: TokenClaims = Depends(get_current_claims)) -> TokenClaims:
        if claims.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{claims.role.value}' is not permitted to access this resource",
            )
        return claims

    return _check
