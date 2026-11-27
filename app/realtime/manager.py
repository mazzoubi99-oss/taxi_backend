"""
ConnectionManager — إدارة WebSocket connections + rooms
"""
import asyncio
import logging
from collections import defaultdict
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    يدير:
    - rooms: channel → set of websockets
    - user_ws: user_id → set of websockets (لإرسال إشعارات لمستخدم)
    """

    def __init__(self):
        # channel → set(WebSocket)
        self.rooms: dict[str, set[WebSocket]] = defaultdict(set)
        # user_id → set(WebSocket)
        self.user_ws: dict[str, set[WebSocket]] = defaultdict(set)
        # WebSocket → channels (للتنظيف السريع)
        self.ws_channels: dict[WebSocket, set[str]] = defaultdict(set)
        # WebSocket → user_id
        self.ws_user: dict[WebSocket, str] = {}
        # قفل للتزامن
        self._lock = asyncio.Lock()

    # ===== Connect / Disconnect =====
    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            self.ws_user[websocket] = user_id
            self.user_ws[user_id].add(websocket)
        logger.info(f"WS connected: user={user_id}, total_users={len(self.user_ws)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            user_id = self.ws_user.pop(websocket, None)

            if user_id:
                self.user_ws[user_id].discard(websocket)
                if not self.user_ws[user_id]:
                    del self.user_ws[user_id]

            for channel in self.ws_channels.pop(websocket, set()):
                self.rooms[channel].discard(websocket)
                if not self.rooms[channel]:
                    del self.rooms[channel]

        if user_id:
            logger.info(f"WS disconnected: user={user_id}")

    # ===== Rooms =====
    async def join_room(self, websocket: WebSocket, channel: str) -> None:
        async with self._lock:
            self.rooms[channel].add(websocket)
            self.ws_channels[websocket].add(channel)

    async def leave_room(self, websocket: WebSocket, channel: str) -> None:
        async with self._lock:
            self.rooms[channel].discard(websocket)
            if not self.rooms[channel]:
                del self.rooms[channel]
            self.ws_channels[websocket].discard(channel)

    # ===== Broadcast =====
    async def broadcast(self, channel: str, message: dict) -> int:
        """يبث لرووم. يرجع عدد اللي وصلهم."""
        if channel not in self.rooms:
            return 0

        targets = list(self.rooms[channel])
        disconnected = []

        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"broadcast send failed: {e}")
                disconnected.append(ws)

        for ws in disconnected:
            await self.disconnect(ws)

        return len(targets) - len(disconnected)

    async def send_to_user(self, user_id: str, message: dict) -> int:
        """يبعت لمستخدم معين (كل أجهزته)."""
        if user_id not in self.user_ws:
            return 0

        targets = list(self.user_ws[user_id])
        disconnected = []

        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"send_to_user failed: {e}")
                disconnected.append(ws)

        for ws in disconnected:
            await self.disconnect(ws)

        return len(targets) - len(disconnected)

    async def send_to_user_in_room(
        self, user_id: str, channel: str, message: dict
    ) -> int:
        """يبعت لمستخدم معين بس اللي موجود في room محدد."""
        if user_id not in self.user_ws:
            return 0

        room = self.rooms.get(channel, set())
        targets = [ws for ws in self.user_ws[user_id] if ws in room]

        count = 0
        for ws in targets:
            try:
                await ws.send_json(message)
                count += 1
            except Exception:
                await self.disconnect(ws)

        return count

    # ===== Stats =====
    def stats(self) -> dict:
        return {
            "total_users": len(self.user_ws),
            "total_rooms": len(self.rooms),
            "rooms": {
                ch: len(ws_set) for ch, ws_set in self.rooms.items()
            },
        }


# ===== Singleton =====
manager = ConnectionManager()