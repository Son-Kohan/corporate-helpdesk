from collections import defaultdict
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.auth import has_permission
from app.database import AsyncSessionLocal
from app.models import Ticket, User
from app.security import decode_access_token


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, ticket_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections[ticket_id].add(websocket)

    def disconnect(self, ticket_id: str, websocket: WebSocket) -> None:
        self.active_connections[ticket_id].discard(websocket)
        if not self.active_connections[ticket_id]:
            self.active_connections.pop(ticket_id, None)

    def disconnect_everywhere(self, websocket: WebSocket) -> None:
        for ticket_id in list(self.active_connections):
            self.disconnect(ticket_id, websocket)

    async def broadcast(self, ticket_id: str, message: dict[str, Any]) -> None:
        targets = set(self.active_connections.get(ticket_id, set()))
        targets.update(self.active_connections.get("all", set()))
        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect_everywhere(websocket)


manager = ConnectionManager()


async def authenticate_websocket(websocket: WebSocket, ticket_id: str) -> User | None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return None
    try:
        username = decode_access_token(token)
    except ValueError:
        await websocket.close(code=1008)
        return None

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if not user or not user.is_active:
            await websocket.close(code=1008)
            return None
        if ticket_id != "all":
            try:
                numeric_ticket_id = int(ticket_id)
            except ValueError:
                await websocket.close(code=1008)
                return None
            ticket = await db.get(Ticket, numeric_ticket_id)
            can_read = ticket and (
                await has_permission(user, "tickets.read_all", db)
                or (ticket.created_by == user.id and await has_permission(user, "tickets.read_own", db))
                or (ticket.assigned_to == user.id and await has_permission(user, "tickets.read_assigned", db))
            )
            if not can_read:
                await websocket.close(code=1008)
                return None
        return user


async def websocket_endpoint(websocket: WebSocket, ticket_id: str) -> None:
    if not await authenticate_websocket(websocket, ticket_id):
        return
    await manager.connect(ticket_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ticket_id, websocket)
