"""
WS Notify — دوال إرسال رسائل WebSocket من الخدمات
"""
import logging
from datetime import datetime, timezone

from app.realtime.manager import manager

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ===== Trip events =====
async def notify_trip_created(trip_id: str, trip_data: dict):
    """رحلة جديدة — للأدمن."""
    await manager.broadcast("admin:trips", {
        "type": "trip_created",
        "trip_id": trip_id,
        "trip": trip_data,
        "at": _now_iso(),
    })


async def notify_driver_offer(driver_id: str, trip_id: str, offer_data: dict):
    """عرض رحلة جديدة — للسائق."""
    await manager.send_to_user(driver_id, {
        "type": "trip_offer",
        "trip_id": trip_id,
        **offer_data,
        "at": _now_iso(),
    })
    # كمان في room السائق
    await manager.broadcast(f"driver:{driver_id}", {
        "type": "trip_offer",
        "trip_id": trip_id,
        **offer_data,
        "at": _now_iso(),
    })


async def notify_trip_accepted(trip_id: str, driver_data: dict, rider_id: str, driver_id: str):
    """السائق قبل — للراكب + للسائق + للأدمن."""
    # للراكب (trip room)
    await manager.broadcast(f"trip:{trip_id}", {
        "type": "trip_accepted",
        "trip_id": trip_id,
        "driver": driver_data,
        "at": _now_iso(),
    })

    # للسائق (على user channel)
    await manager.send_to_user(driver_id, {
        "type": "trip_accepted_driver",
        "trip_id": trip_id,
        "at": _now_iso(),
    })

    # للأدمن
    await manager.broadcast("admin:trips", {
        "type": "trip_status",
        "trip_id": trip_id,
        "status": "accepted",
        "at": _now_iso(),
    })


async def notify_trip_status(trip_id: str, status: str, extra: dict = None):
    """تحديث حالة الرحلة — للراكب + السائق + الأدمن."""
    await manager.broadcast(f"trip:{trip_id}", {
        "type": "trip_status",
        "trip_id": trip_id,
        "status": status,
        "extra": extra,
        "at": _now_iso(),
    })
    await manager.broadcast("admin:trips", {
        "type": "trip_status",
        "trip_id": trip_id,
        "status": status,
        "extra": extra,
        "at": _now_iso(),
    })


async def notify_trip_completed(trip_id: str, price_final: float):
    await manager.broadcast(f"trip:{trip_id}", {
        "type": "trip_completed",
        "trip_id": trip_id,
        "price_final": price_final,
        "at": _now_iso(),
    })
    await manager.broadcast("admin:trips", {
        "type": "trip_status",
        "trip_id": trip_id,
        "status": "completed",
        "extra": {"price_final": price_final},
        "at": _now_iso(),
    })


async def notify_trip_cancelled(trip_id: str, reason: str = None, by: str = None,
                                 rider_id: str = None, driver_id: str = None):
    await manager.broadcast(f"trip:{trip_id}", {
        "type": "trip_cancelled",
        "trip_id": trip_id,
        "reason": reason,
        "by": by,
        "at": _now_iso(),
    })
    await manager.broadcast("admin:trips", {
        "type": "trip_status",
        "trip_id": trip_id,
        "status": "cancelled",
        "extra": {"reason": reason, "by": by},
        "at": _now_iso(),
    })


async def notify_trip_taken(trip_id: str, excluded_driver: str = None):
    """رحلة اتمنحت لسائق تاني — لكل السائقين التانيين اللي عندهم offer."""
    # للأدمن فقط — السائقين الآخرين ياخدوا رسالة عبر offers
    await manager.broadcast("admin:trips", {
        "type": "trip_status",
        "trip_id": trip_id,
        "status": "taken",
        "at": _now_iso(),
    })


async def notify_offer_expired(driver_id: str, trip_id: str):
    await manager.send_to_user(driver_id, {
        "type": "trip_offer_expired",
        "trip_id": trip_id,
        "at": _now_iso(),
    })


# ===== Notification event =====
async def notify_user_notification(user_id: str, notification: dict):
    """إشعار جديد — للمستخدم."""
    await manager.send_to_user(user_id, {
        "type": "notification",
        "notification": notification,
        "at": _now_iso(),
    })