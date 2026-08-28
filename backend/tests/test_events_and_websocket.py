"""
docs/PRODUCT_EXPERIENCE.md §4's real-time proof, at two levels: the event
dispatcher itself (unit-level), and the full WebSocket delivery path
(integration-level, matching this phase's required "investigator receiving
a new incident" test).
"""
import asyncio
import queue
import threading

import pytest

from app.events.dispatcher import EventDispatcher
from app.db.models.enums import UserRole
from tests.conftest import make_token, valid_complaint_payload


def test_dispatcher_delivers_published_event_to_subscriber():
    dispatcher = EventDispatcher()
    received = []

    async def handler(payload):
        received.append(payload)

    dispatcher.subscribe("complaint.created", handler)
    asyncio.run(dispatcher.publish("complaint.created", {"complaint_id": "abc123"}))

    assert received == [{"complaint_id": "abc123"}]


def test_dispatcher_does_not_deliver_to_unrelated_topic():
    dispatcher = EventDispatcher()
    received = []

    async def handler(payload):
        received.append(payload)

    dispatcher.subscribe("some.other.topic", handler)
    asyncio.run(dispatcher.publish("complaint.created", {"complaint_id": "abc123"}))

    assert received == []


def test_dispatcher_one_failing_subscriber_does_not_block_others():
    dispatcher = EventDispatcher()
    received = []

    async def failing_handler(payload):
        raise RuntimeError("boom")

    async def working_handler(payload):
        received.append(payload)

    dispatcher.subscribe("complaint.created", failing_handler)
    dispatcher.subscribe("complaint.created", working_handler)
    asyncio.run(dispatcher.publish("complaint.created", {"complaint_id": "abc123"}))

    assert received == [{"complaint_id": "abc123"}]


def _receive_with_timeout(websocket, timeout=2.0):
    """Starlette's synchronous WebSocket test session blocks indefinitely on
    receive() if nothing arrives - run it in a *daemon* thread so "no
    message was sent" can be asserted without hanging the test suite.

    Deliberately not a `concurrent.futures.ThreadPoolExecutor` context
    manager here: its `__exit__` calls `shutdown(wait=True)`, which would
    block the whole test process on exactly the still-blocked receive() call
    this helper exists to time out on. A plain daemon `threading.Thread` can
    be abandoned - the interpreter doesn't wait for daemon threads to exit.
    """
    result_queue: "queue.Queue" = queue.Queue(maxsize=1)

    def _worker():
        try:
            result_queue.put(("ok", websocket.receive_json()))
        except Exception as exc:  # connection closed, etc.
            result_queue.put(("error", exc))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    try:
        status, value = result_queue.get(timeout=timeout)
    except queue.Empty:
        return None
    if status == "error":
        raise value
    return value


def test_investigator_receives_new_complaint_over_websocket_without_refresh(client, jurisdiction_a):
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)

    with client.websocket_connect(f"/v1/ws?token={token}") as websocket:
        response = client.post(
            "/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai")
        )
        assert response.status_code == 201

        message = _receive_with_timeout(websocket)
        assert message is not None, "investigator did not receive the live push"
        assert message["type"] == "complaint.created"
        assert message["complaint_id"] == response.json()["complaint_id"]
        assert message["incident_reference"] == response.json()["incident_reference"]


def test_investigator_in_a_different_jurisdiction_does_not_receive_the_push(
    client, jurisdiction_a, jurisdiction_b
):
    other_token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_b.jurisdiction_id)

    with client.websocket_connect(f"/v1/ws?token={other_token}") as websocket:
        response = client.post(
            "/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai")
        )
        assert response.status_code == 201

        message = _receive_with_timeout(websocket, timeout=1.5)
        assert message is None, f"jurisdiction B investigator should not have received {message}"


def test_websocket_connection_rejected_without_valid_token(client, jurisdiction_a):
    with pytest.raises(Exception):
        with client.websocket_connect("/v1/ws?token=garbage") as websocket:
            websocket.receive_json()
