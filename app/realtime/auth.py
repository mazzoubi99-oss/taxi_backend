"""
WebSocket auth — JWT عبر أول رسالة
"""
import asyncio
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.core.security import decode_token

logger = logging.getLogger(__name__)

AUTH_TIMEOUT_SECONDS = 10


async def authenticate_ws(websocket: WebSocket) -> Optional[dict]:
    """
    ينتظر أول رسالة من العميل — لازم تكون {"type": "auth", "token": "..."}.
    يرجع payload لو نجح، None لو فشل.
    """
    try:
        raw = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=AUTH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("WS auth timeout")
        return None
    except Exception as e:
        logger.warning(f"WS auth error: {e}")
        return None

    if not isinstance(raw, dict) or raw.get("type") != "auth":
        return None

    token = raw.get("token")
    if not token:
        return None

    payload = decode_token(token, token_type="access")
    if not payload:
        return None

    return payload