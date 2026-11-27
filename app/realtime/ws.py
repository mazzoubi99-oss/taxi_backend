"""
WebSocket endpoints — 4 قنوات
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import db_cursor
from app.realtime.auth import authenticate_ws
from app.realtime.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# Helper: بناء رسالة
# ============================================================
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 1) WS /ws/trip/{trip_id} — تتبع حي (راكب + سائق)
# ============================================================
@router.websocket("/ws/trip/{trip_id}")
async def ws_trip(websocket: WebSocket, trip_id: str):
    user = await authenticate_ws(websocket)
    if not user:
        await websocket.close(code=1008)
        return

    user_id = user["sub"]
    role = user.get("role")

    # تحقق من صلاحية الوصول للرحلة
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT rider_id, driver_id, status FROM trips WHERE id = %s",
            (trip_id,),
        )
        trip = cur.fetchone()

    if not trip:
        await websocket.close(code=1008)
        return

    rider_id = str(trip["rider_id"])
    driver_id = str(trip["driver_id"]) if trip["driver_id"] else None

    if user_id not in (rider_id, driver_id) and role != "admin":
        await websocket.close(code=1008)
        return

    # connect
    await manager.connect(websocket, user_id)
    channel = f"trip:{trip_id}"
    await manager.join_room(websocket, channel)

    # ابعت الحالة الحالية فوراً
    try:
        await websocket.send_json({
            "type": "trip_snapshot",
            "trip_id": trip_id,
            "status": trip["status"],
            "at": _now_iso(),
        })
    except Exception:
        pass

    # استقبل التحديثات
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "at": _now_iso()})
                continue

            if msg_type == "location_update" and user_id == driver_id:
                # السائق يبعت موقعه → نحدث DB + نبث للراكب
                await _handle_driver_location(trip_id, driver_id, data)
                continue

            # رسائل أخرى — نتجاهلها
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"ws_trip error: {e}")
    finally:
        await manager.leave_room(websocket, channel)
        await manager.disconnect(websocket)


async def _handle_driver_location(trip_id: str, driver_id: str, data: dict):
    """معالجة location_update من السائق."""
    try:
        lat = float(data["lat"])
        lng = float(data["lng"])
        heading = data.get("heading")
        speed = data.get("speed")
    except (KeyError, ValueError, TypeError):
        return

    now_iso = _now_iso()

    # 1) خزّن في trip_locations (كل 10 ثواني كحد أقصى)
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT recorded_at FROM trip_locations
            WHERE trip_id = %s ORDER BY recorded_at DESC LIMIT 1
            """,
            (trip_id,),
        )
        last = cur.fetchone()

        should_save = True
        if last and last["recorded_at"]:
            last_at = last["recorded_at"]
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last_at).total_seconds()
            if elapsed < 10:
                should_save = False

        if should_save:
            cur.execute(
                """
                INSERT INTO trip_locations
                    (trip_id, driver_id, lat, lng, location, heading, speed)
                VALUES (%s, %s, %s, %s,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        %s, %s)
                """,
                (trip_id, driver_id, lat, lng, lng, lat, heading, speed),
            )

        # 2) حدّث آخر موقع في trips
        cur.execute(
            """
            UPDATE trips
            SET last_driver_location = %s::jsonb
            WHERE id = %s
            """,
            (
                _json_dumps({
                    "lat": lat, "lng": lng,
                    "heading": heading, "speed": speed,
                    "at": now_iso,
                }),
                trip_id,
            ),
        )

    # 3) ابث للراكب في room
    await manager.broadcast(f"trip:{trip_id}", {
        "type": "driver_location",
        "trip_id": trip_id,
        "lat": lat,
        "lng": lng,
        "heading": heading,
        "speed": speed,
        "at": now_iso,
    })


# ============================================================
# 2) WS /ws/driver — عروض الرحلات + تحديث الموقع
# ============================================================
@router.websocket("/ws/driver")
async def ws_driver(websocket: WebSocket):
    user = await authenticate_ws(websocket)
    if not user:
        await websocket.close(code=1008)
        return

    user_id = user["sub"]
    if user.get("role") != "driver":
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, user_id)
    await manager.join_room(websocket, f"driver:{user_id}")

    try:
        await websocket.send_json({
            "type": "connected",
            "user_id": user_id,
            "at": _now_iso(),
        })
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "at": _now_iso()})
                continue

            if msg_type == "location_update":
                # السائق يحدث موقعه العام (بدون رحلة)
                try:
                    lat = float(data["lat"])
                    lng = float(data["lng"])
                except (KeyError, ValueError):
                    continue

                with db_cursor() as cur:
                    cur.execute(
                        """
                        UPDATE drivers
                        SET current_lat = %s,
                            current_lng = %s,
                            current_location = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                            last_location_at = NOW()
                        WHERE user_id = %s
                        """,
                        (lat, lng, lng, lat, user_id),
                    )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"ws_driver error: {e}")
    finally:
        await manager.leave_room(websocket, f"driver:{user_id}")
        await manager.disconnect(websocket)


# ============================================================
# 3) WS /ws/user — إشعارات
# ============================================================
@router.websocket("/ws/user")
async def ws_user(websocket: WebSocket):
    user = await authenticate_ws(websocket)
    if not user:
        await websocket.close(code=1008)
        return

    user_id = user["sub"]
    await manager.connect(websocket, user_id)
    await manager.join_room(websocket, f"user:{user_id}")

    try:
        await websocket.send_json({
            "type": "connected",
            "user_id": user_id,
            "at": _now_iso(),
        })
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong", "at": _now_iso()})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"ws_user error: {e}")
    finally:
        await manager.leave_room(websocket, f"user:{user_id}")
        await manager.disconnect(websocket)


# ============================================================
# 4) WS /ws/admin/trips — مراقبة كل الرحلات
# ============================================================
@router.websocket("/ws/admin/trips")
async def ws_admin_trips(websocket: WebSocket):
    user = await authenticate_ws(websocket)
    if not user:
        await websocket.close(code=1008)
        return

    if user.get("role") != "admin":
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, user["sub"])
    await manager.join_room(websocket, "admin:trips")

    try:
        await websocket.send_json({
            "type": "connected",
            "at": _now_iso(),
        })
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong", "at": _now_iso()})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"ws_admin_trips error: {e}")
    finally:
        await manager.leave_room(websocket, "admin:trips")
        await manager.disconnect(websocket)


# ============================================================
# Helpers
# ============================================================
def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)