"""
docs/API_CONTRACT.md §7 real-time gateway, scoped to what Phase 1 needs:
the `complaint.created` push. Auth via a `token` query param (WebSocket
handshakes can't carry a custom Authorization header from a browser
client) - same JWT the REST API uses, no separate WS-only credential.
"""
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.logging_config import get_logger
from app.core.security import decode_access_token
from app.db.models.enums import UserRole
from app.ws.manager import manager

router = APIRouter(tags=["realtime"])
logger = get_logger(__name__)


@router.websocket("/v1/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    jurisdiction_id: Optional[str] = Query(default=None),
):
    payload = decode_access_token(token)
    if payload is None:
        logger.error("WebSocket rejected: payload is None")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    role = payload.get("role")
    claim_jurisdiction = payload.get("jurisdiction_id")

    if role in (UserRole.investigator.value, UserRole.supervisor.value):
        target_jurisdiction = claim_jurisdiction
    else:
        target_jurisdiction = jurisdiction_id

    if not target_jurisdiction:
        logger.error("WebSocket rejected: no target_jurisdiction")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return


    await manager.connect(target_jurisdiction, websocket)
    try:
        while True:
            # Nothing meaningful is expected from the client; this just
            # blocks until disconnect so we notice a closed connection.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(target_jurisdiction, websocket)
