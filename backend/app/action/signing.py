"""
HMAC-SHA256 webhook signing - docs/SECURITY_AND_GOVERNANCE.md §7: "HMAC-SHA256
signature header on every outbound alert payload, verified by the receiver."
Mirrors app/audit/service.py's own canonical-JSON discipline (sorted keys,
compact separators) so signing is deterministic regardless of dict
insertion order.
"""
import hashlib
import hmac
import json

from app.core.config import get_settings

settings = get_settings()


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def sign_payload(payload: dict) -> str:
    """`payload` must never itself contain a `signature` key - the
    signature is computed over everything else, then attached separately."""
    body = _canonical_json(payload)
    return hmac.new(settings.webhook_hmac_secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(payload: dict, signature: str) -> bool:
    """Constant-time comparison - a timing side-channel on webhook
    signature checks is a real, if minor, attack surface worth closing for
    free via hmac.compare_digest."""
    if not signature:
        return False
    expected = sign_payload(payload)
    return hmac.compare_digest(expected, signature)
