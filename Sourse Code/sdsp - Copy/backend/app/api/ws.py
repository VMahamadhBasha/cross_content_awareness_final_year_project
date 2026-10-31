"""WebSocket hub broadcasting live alerts to dashboard clients."""
import logging

from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionHub:
    """Tracks connected dashboard clients and fans out messages."""

    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a client."""
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a client."""
        self.connections.discard(ws)

    async def broadcast(self, message: dict) -> None:
        """Send a message to every connected client, dropping dead connections."""
        for ws in list(self.connections):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)
