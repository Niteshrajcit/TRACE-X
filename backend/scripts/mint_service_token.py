"""
Mints a `service`-role JWT out-of-band (docs/SECURITY_AND_GOVERNANCE.md §3) -
there is no human account behind the synthetic harness or a future bank/NCRP
adapter, so this token is never issued through POST /v1/auth/login.

Usage:
    python scripts/mint_service_token.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import create_access_token  # noqa: E402


def main() -> None:
    token = create_access_token(
        {"sub": "synthetic-harness", "role": "service", "jurisdiction_id": None, "bank_id": None},
        expires_minutes=60 * 24 * 365,  # long-lived - this is a machine credential, not a demo login
    )
    print(token)


if __name__ == "__main__":
    main()
