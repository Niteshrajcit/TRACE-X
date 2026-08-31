"""
Unit tests for the Fast2SMS citizen SMS confirmation module and integration.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from app.shared.sms import (
    MAX_SMS_LENGTH,
    clean_phone_number,
    format_complaint_sms_message,
    send_sms_async,
    send_sms_sync,
)
from tests.conftest import valid_complaint_payload


def test_clean_phone_number_formats():
    # Valid Indian formats
    assert clean_phone_number("9876543210") == "9876543210"
    assert clean_phone_number("+91 9876543210") == "9876543210"
    assert clean_phone_number("+91-98765-43210") == "9876543210"
    assert clean_phone_number("919876543210") == "9876543210"
    assert clean_phone_number("09876543210") == "9876543210"
    assert clean_phone_number("  98765 43210 ") == "9876543210"

    # Invalid formats
    assert clean_phone_number(None) is None
    assert clean_phone_number("") is None
    assert clean_phone_number("12345") is None
    assert clean_phone_number("abcdefghij") is None
    assert clean_phone_number("+1 555-123-4567") is None


def test_format_complaint_sms_message():
    ref_id = "TX-2026-A1B2C3D4"
    msg = format_complaint_sms_message(ref_id)

    assert ref_id in msg
    assert "TRACE-X" in msg
    assert "registered" in msg
    assert len(msg) <= MAX_SMS_LENGTH


@pytest.mark.asyncio
async def test_send_sms_async_no_api_key():
    with patch("app.shared.sms.get_settings") as mock_settings:
        mock_settings.return_value.fast2sms_api_key = None
        with patch.dict("os.environ", {}, clear=True):
            result = await send_sms_async("9876543210", "TX-2026-12345678", api_key=None)
            assert result["status"] == "skipped"
            assert result["reason"] == "no_api_key"


@pytest.mark.asyncio
async def test_send_sms_async_invalid_phone():
    result = await send_sms_async("invalid", "TX-2026-12345678", api_key="dummy_key")
    assert result["status"] == "skipped"
    assert result["reason"] == "invalid_phone"


@pytest.mark.asyncio
async def test_send_sms_async_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "return": True,
        "request_id": "req-12345",
        "message": ["SMS sent successfully."],
    }
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await send_sms_async(
            phone="+91 9876543210",
            reference_id="TX-2026-12345678",
            api_key="test_fast2sms_key",
        )
        assert result["status"] == "success"
        assert result["response"]["return"] is True

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["headers"]["authorization"] == "test_fast2sms_key"
        assert call_kwargs["json"]["numbers"] == "9876543210"
        assert "TX-2026-12345678" in call_kwargs["json"]["message"]
        assert call_kwargs["json"]["route"] == "q"


@pytest.mark.asyncio
async def test_send_sms_async_network_failure():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Network unreachable")
        result = await send_sms_async(
            phone="9876543210",
            reference_id="TX-2026-12345678",
            api_key="test_key",
        )
        assert result["status"] == "failed"
        assert "Network unreachable" in result["error"]


def test_send_sms_sync_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"return": True, "message": ["SMS sent successfully."]}

    with patch("httpx.Client.post") as mock_post:
        mock_post.return_value = mock_resp
        result = send_sms_sync(
            phone="9876543210",
            reference_id="TX-2026-12345678",
            api_key="test_key",
        )
        assert result["status"] == "success"


def test_complaint_intake_dispatches_sms_background_task(client, db):
    payload = valid_complaint_payload()
    payload["victim_phone"] = "+91 98765 43210"

    with patch("app.modules.complaints.router.send_sms_async", new_callable=AsyncMock) as mock_sms:
        response = client.post("/v1/complaints", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert "incident_reference" in data
