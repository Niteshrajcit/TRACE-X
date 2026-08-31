"""
Fast2SMS Quick Route integration for citizen incident notifications.

Dispatches instant SMS notifications when a citizen files a complaint.
Adheres to Fast2SMS Developer Quick Route (route: "q") rules:
- Approved neutral phrasing to bypass telecom spam filters.
- Message length strictly bounded under 160 characters (1 SMS credit).
- Automatic phone number sanitization to 10-digit Indian mobile standard.
- Non-blocking asynchronous dispatch with fallback error handling.
"""
import logging
import os
import re
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger("tracex.sms")

FAST2SMS_API_URL = "https://www.fast2sms.com/dev/bulkV2"
MAX_SMS_LENGTH = 160


def clean_phone_number(phone: Optional[str]) -> Optional[str]:
    """
    Sanitizes phone input to a standard 10-digit Indian mobile number.
    Strips country code (+91 / 91), leading zero, whitespace, and special characters.
    Returns 10-digit string if valid, or None if invalid.
    """
    if not phone:
        return None

    # Keep only digits
    digits = re.sub(r"\D", "", phone)

    # Strip country code +91 or 91 if 12 digits
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    # Strip leading 0 if 11 digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    # Must be exactly 10 digits
    if len(digits) == 10:
        return digits

    return None


def format_complaint_sms_message(reference_id: str) -> str:
    """
    Generates a clean, telecom-approved confirmation SMS message.
    Guarantees:
    - Pure ASCII characters (prevents Unicode 70-char billing downgrade).
    - Length strictly capped at <= 160 characters (guarantees exactly 1 credit / ~0.20 INR cost).
    """
    # Sanitize reference ID to standard alphanumeric/hyphen
    clean_ref = "".join(ch for ch in reference_id if ch.isalnum() or ch in "-_")
    message = (
        f"TRACE-X Portal: Your incident report has been successfully registered. "
        f"Reference ID: {clean_ref}. Keep this for your case updates."
    )
    # Strip any non-ASCII characters that might trigger Unicode UCS-2 pricing
    message = message.encode("ascii", "ignore").decode("ascii")

    if len(message) > MAX_SMS_LENGTH:
        message = f"TRACE-X: Incident registered. Ref: {clean_ref}. Keep for updates."
        message = message[:MAX_SMS_LENGTH]

    return message


async def send_sms_async(
    phone: str,
    reference_id: str,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Asynchronously sends an SMS via Fast2SMS Quick Route.
    Safe against exceptions to prevent impacting the caller.
    """
    key = api_key or get_settings().fast2sms_api_key or os.getenv("FAST2SMS_API_KEY")
    if not key:
        logger.warning("FAST2SMS_API_KEY not configured. Skipping SMS dispatch.")
        return {"status": "skipped", "reason": "no_api_key"}

    cleaned_phone = clean_phone_number(phone)
    if not cleaned_phone:
        logger.warning("Invalid phone number format for SMS dispatch: %s", phone)
        return {"status": "skipped", "reason": "invalid_phone"}

    message_text = format_complaint_sms_message(reference_id)

    headers = {
        "authorization": key,
        "Content-Type": "application/json",
    }
    payload = {
        "route": "q",
        "message": message_text,
        "language": "english",
        "flash": 0,
        "numbers": cleaned_phone,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(FAST2SMS_API_URL, headers=headers, json=payload)
            response_data = response.json()
            logger.info(
                "Fast2SMS response for ref %s (phone %s...): %s",
                reference_id,
                cleaned_phone[:4],
                response_data,
            )
            return {"status": "success", "response": response_data}
    except Exception as exc:
        logger.error(
            "Failed to send Fast2SMS notification for ref %s: %s",
            reference_id,
            exc,
            exc_info=True,
        )
        return {"status": "failed", "error": str(exc)}


def send_sms_sync(
    phone: str,
    reference_id: str,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Synchronous version of SMS dispatch.
    """
    key = api_key or get_settings().fast2sms_api_key or os.getenv("FAST2SMS_API_KEY")
    if not key:
        logger.warning("FAST2SMS_API_KEY not configured. Skipping SMS dispatch.")
        return {"status": "skipped", "reason": "no_api_key"}

    cleaned_phone = clean_phone_number(phone)
    if not cleaned_phone:
        logger.warning("Invalid phone number format for SMS dispatch: %s", phone)
        return {"status": "skipped", "reason": "invalid_phone"}

    message_text = format_complaint_sms_message(reference_id)

    headers = {
        "authorization": key,
        "Content-Type": "application/json",
    }
    payload = {
        "route": "q",
        "message": message_text,
        "language": "english",
        "flash": 0,
        "numbers": cleaned_phone,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(FAST2SMS_API_URL, headers=headers, json=payload)
            response_data = response.json()
            logger.info(
                "Fast2SMS sync response for ref %s (phone %s...): %s",
                reference_id,
                cleaned_phone[:4],
                response_data,
            )
            return {"status": "success", "response": response_data}
    except Exception as exc:
        logger.error(
            "Failed to send Fast2SMS sync notification for ref %s: %s",
            reference_id,
            exc,
            exc_info=True,
        )
        return {"status": "failed", "error": str(exc)}
