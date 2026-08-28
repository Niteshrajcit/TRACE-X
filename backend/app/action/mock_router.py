"""
docs/DEMO_ARCHITECTURE.md §4: "One lightweight service (`mock-external-systems`)
exposing one route per channel (`/mock/bank`, `/mock/i4c`, `/mock/exchange`,
`/mock/merchant`)... Each route independently accepts the exact
signed-webhook payload shape a real integration would, logs receipt."
Collapsed into this backend process per docs/ARCHITECTURE.md §1's modular-
monolith reasoning - a separate container for four stateless, few-line
verify-and-acknowledge routes would add operational risk for zero benefit
at this scale, exactly the same argument already made for the event bus
(docs/PRODUCT_EXPERIENCE.md §8.1).

HMAC-signed, not JWT (docs/API_CONTRACT.md's own preamble: "the
mock-institution webhook receivers (HMAC-signed, not JWT)") - no auth
dependency here at all, the signature check IS the auth.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, status

from app.action.signing import verify_signature
from app.core.logging_config import get_logger
from app.db.models.enums import AlertChannel

logger = get_logger(__name__)

router = APIRouter(prefix="/mock", tags=["mock-external-systems"])


def _receive(channel: AlertChannel, payload: dict, x_signature: str) -> dict:
    verifiable = {k: v for k, v in payload.items() if k != "signature"}
    if not verify_signature(verifiable, x_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    logger.info(
        "mock_receiver.received",
        extra={"extra_fields": {"channel": channel.value, "alert_id": payload.get("alert_id")}},
    )
    return {
        "received": True,
        "channel": channel.value,
        "alert_id": payload.get("alert_id"),
        "acknowledged_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/bank")
async def receive_bank_webhook(payload: dict, x_signature: str = Header(...)) -> dict:
    return _receive(AlertChannel.bank_webhook_sim, payload, x_signature)


@router.post("/i4c")
async def receive_i4c_webhook(payload: dict, x_signature: str = Header(...)) -> dict:
    return _receive(AlertChannel.i4c_webhook_sim, payload, x_signature)


@router.post("/exchange")
async def receive_exchange_webhook(payload: dict, x_signature: str = Header(...)) -> dict:
    return _receive(AlertChannel.exchange_webhook_sim, payload, x_signature)


@router.post("/merchant")
async def receive_merchant_webhook(payload: dict, x_signature: str = Header(...)) -> dict:
    return _receive(AlertChannel.merchant_webhook_sim, payload, x_signature)
