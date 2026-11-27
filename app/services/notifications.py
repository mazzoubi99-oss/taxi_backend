"""
Notification service — إنشاء إشعارات + (لاحقاً) FCM
"""
import logging
from typing import Optional

from app.core.database import db_cursor

logger = logging.getLogger(__name__)


def create_notification(
    recipient_id: str,
    type: str,
    title: str,
    body: str,
    *,
    sender_id: Optional[str] = None,
    sender_type: str = "system",
    data: Optional[dict] = None,
) -> Optional[str]:
    """
    يُنشئ إشعار. يرجع id الإشعار.
    (FCM مؤجل — نسجل فقط)
    """
    try:
        with db_cursor(dict_cursor=True) as cur:
            cur.execute(
                """
                INSERT INTO notifications
                    (recipient_id, sender_id, sender_type, type, title, body, data)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (
                    recipient_id,
                    sender_id,
                    sender_type,
                    type,
                    title,
                    body,
                    data,
                ),
            )
            row = cur.fetchone()
            return str(row["id"]) if row else None
    except Exception as e:
        logger.exception(f"create_notification error: {e}")
        return None


def notify_admins(
    type: str,
    title: str,
    body: str,
    *,
    sender_id: Optional[str] = None,
    sender_type: str = "system",
    data: Optional[dict] = None,
) -> int:
    """يرسل إشعار لكل الأدمنز النشطين. يرجع عددهم."""
    try:
        with db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT id FROM users WHERE role = 'admin' AND is_active = TRUE"
            )
            admins = cur.fetchall()

        count = 0
        for admin in admins:
            if create_notification(
                recipient_id=str(admin["id"]),
                type=type,
                title=title,
                body=body,
                sender_id=sender_id,
                sender_type=sender_type,
                data=data,
            ):
                count += 1
        return count
    except Exception as e:
        logger.exception(f"notify_admins error: {e}")
        return 0


# ===== Helpers جاهزة =====
def notify_driver_approved(admin_id: str, driver_id: str):
    return create_notification(
        recipient_id=driver_id,
        type="driver_approved",
        title="تمت الموافقة على حسابك ✅",
        body="يمكنك الآن تفعيل حالة الاتصال واستقبال الرحلات.",
        sender_id=admin_id,
        sender_type="admin",
    )


def notify_driver_rejected(admin_id: str, driver_id: str, reason: str):
    return create_notification(
        recipient_id=driver_id,
        type="driver_rejected",
        title="تم رفض طلب التوثيق ❌",
        body=f"السبب: {reason}",
        sender_id=admin_id,
        sender_type="admin",
        data={"reason": reason},
    )


def notify_driver_banned(admin_id: str, driver_id: str, reason: str):
    return create_notification(
        recipient_id=driver_id,
        type="driver_banned",
        title="تم حظر حسابك 🚫",
        body=f"السبب: {reason}",
        sender_id=admin_id,
        sender_type="admin",
        data={"reason": reason},
    )


def notify_driver_unbanned(admin_id: str, driver_id: str):
    return create_notification(
        recipient_id=driver_id,
        type="driver_unbanned",
        title="تم رفع الحظر عن حسابك ✅",
        body="يمكنك الآن استخدام التطبيق.",
        sender_id=admin_id,
        sender_type="admin",
    )


def notify_admins_new_driver(driver_id: str, driver_name: str, phone: str):
    """عند تسجيل سائق جديد — إشعار لكل الأدمن."""
    return notify_admins(
        type="new_driver_pending",
        title="سائق جديد بانتظار التوثيق 🚗",
        body=f"السائق: {driver_name} — {phone}",
        sender_type="system",
        data={"driver_id": driver_id},
    )

# ===== Trip Notifications =====

def notify_driver_new_trip(
    driver_id: str,
    trip_id: str,
    pickup_address: str | None,
    price: float,
    distance_to_pickup: float,
):
    """إشعار للسائق برحلة جديدة."""
    return create_notification(
        recipient_id=driver_id,
        type="trip_offer",
        title="رحلة جديدة 🚗",
        body=f"من: {pickup_address or 'موقع'} — السعر: {price:.0f} — المسافة إليك: {int(distance_to_pickup)}م",
        sender_type="system",
        data={"trip_id": trip_id, "price": price, "distance_meters": int(distance_to_pickup)},
    )


def notify_rider_driver_accepted(rider_id: str, trip_id: str, driver_name: str):
    return create_notification(
        recipient_id=rider_id,
        type="trip_accepted",
        title="السائق قبل رحلتك ✅",
        body=f"السائق: {driver_name} في الطريق إليك.",
        sender_type="system",
        data={"trip_id": trip_id},
    )


def notify_driver_trip_accepted(driver_id: str, trip_id: str):
    return create_notification(
        recipient_id=driver_id,
        type="trip_accepted_driver",
        title="تم قبول الرحلة ✅",
        body="توجه الآن لنقطة الراكب.",
        sender_type="system",
        data={"trip_id": trip_id},
    )


def notify_rider_driver_arrived(rider_id: str, trip_id: str):
    return create_notification(
        recipient_id=rider_id,
        type="trip_arrived",
        title="السائق وصل 📍",
        body="السائق في نقطة الالتقاء. أعطه كود البدء.",
        sender_type="system",
        data={"trip_id": trip_id},
    )


def notify_rider_trip_started(rider_id: str, trip_id: str):
    return create_notification(
        recipient_id=rider_id,
        type="trip_started",
        title="بدأت الرحلة 🛣️",
        body="رحلة سعيدة!",
        sender_type="system",
        data={"trip_id": trip_id},
    )


def notify_rider_trip_completed(rider_id: str, trip_id: str, price: float):
    return create_notification(
        recipient_id=rider_id,
        type="trip_completed",
        title="انتهت الرحلة ✅",
        body=f"المبلغ: {price:.0f}. شكراً لاستخدامك التطبيق!",
        sender_type="system",
        data={"trip_id": trip_id, "price": price},
    )


def notify_driver_trip_completed(driver_id: str, trip_id: str, price: float):
    return create_notification(
        recipient_id=driver_id,
        type="trip_completed_driver",
        title="انتهت الرحلة ✅",
        body=f"المبلغ: {price:.0f}. عمولة المنصة خُصمت من محفظتك.",
        sender_type="system",
        data={"trip_id": trip_id, "price": price},
    )


def notify_driver_trip_cancelled(driver_id: str, trip_id: str, reason: str):
    return create_notification(
        recipient_id=driver_id,
        type="trip_cancelled_driver",
        title="تم إلغاء الرحلة ❌",
        body=f"السبب: {reason}",
        sender_type="system",
        data={"trip_id": trip_id, "reason": reason},
    )