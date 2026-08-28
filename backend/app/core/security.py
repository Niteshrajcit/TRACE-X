"""
Password hashing and JWT issuance/verification.

Uses `bcrypt` directly rather than passlib's bcrypt wrapper: passlib 1.7.4's
version-detection shim is incompatible with bcrypt>=4.1 (raises on hash/verify
- a known upstream issue, not a TRACE-X bug), and passlib is otherwise
providing nothing here we can't do in ~15 lines. One less dependency, one
less version-compatibility trap for whoever runs `pip install` next.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()

BCRYPT_MAX_BYTES = 72  # bcrypt's own hard limit


def hash_password(plain_password: str) -> str:
    truncated = plain_password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    truncated = plain_password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(truncated, password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(claims: dict[str, Any], expires_minutes: Optional[int] = None) -> str:
    """JWT claims per docs/API_CONTRACT.md §6: sub, role, jurisdiction_id,
    bank_id, exp. No refresh token / revocation list in this phase - see
    docs/SECURITY_AND_GOVERNANCE.md §3 and docs/PRODUCT_EXPERIENCE.md §8.2."""
    to_encode = claims.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.jwt_expire_minutes
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def hash_pii(value: str) -> str:
    """Irreversible hash for account numbers / phone / email at the ingestion
    boundary (docs/SECURITY_AND_GOVERNANCE.md §2, docs/DATA_MODEL.md §6).
    Server-side pepper means the hash cannot be dictionary-attacked purely
    from a leaked database dump."""
    normalized = value.strip().lower().encode("utf-8")
    peppered = normalized + settings.pii_hash_pepper.encode("utf-8")
    return hashlib.sha256(peppered).hexdigest()
