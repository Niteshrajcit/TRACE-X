"""
Jurisdiction-scoped WebSocket fan-out. docs/ARCHITECTURE.md §5: connections
are terminated here, one channel per jurisdiction; the gateway subscribes to
the in-process event dispatcher and pushes to every matching connection -
no polling anywhere in this design.
"""
from collections import defaultdict
from typing import DefaultDict, Set

from fastapi import WebSocket

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: DefaultDict[str, Set[WebSocket]] = defaultdict(set)

    async def connect(self, jurisdiction_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[jurisdiction_id].add(websocket)
        logger.info(
            "ws.connected",
            extra={"extra_fields": {"jurisdiction_id": jurisdiction_id}},
        )

    def disconnect(self, jurisdiction_id: str, websocket: WebSocket) -> None:
        self._connections[jurisdiction_id].discard(websocket)
        logger.info(
            "ws.disconnected",
            extra={"extra_fields": {"jurisdiction_id": jurisdiction_id}},
        )

    async def broadcast(self, jurisdiction_id: str, message: dict) -> None:
        dead: Set[WebSocket] = set()
        for connection in list(self._connections.get(jurisdiction_id, set())):
            try:
                await connection.send_json(message)
            except Exception:
                dead.add(connection)
        for connection in dead:
            self._connections[jurisdiction_id].discard(connection)

    def connection_count(self, jurisdiction_id: str) -> int:
        return len(self._connections.get(jurisdiction_id, set()))


# Process-wide singleton.
manager = ConnectionManager()
