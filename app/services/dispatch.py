"""
Dispatch service — إرسال العروض للسائقين + اختيار الأفضل
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.database import db_cursor
from app.services import priority as priority_service
from app.services import settings

logger = logging.getLogger(__name__)


# ===== Start code =====
def generate_start_code() -> Optional[str]:
    """يولّد كود بدء الرحلة لو مفعّل، وإلا None."""
    if not settings.get_bool("trips.start_code_enabled", True):
        return None
    length = settings.get_int("trips.start_code_length", 4)
    if length < 2 or length > 8:
        length = 4
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


# ===== Find + rank nearby drivers =====
def find_and_rank_drivers(
    pickup_lat: float,
    pickup_lng: float,
    car_type: Optional[str] = None,
) -> list[dict]:
    """يجيب السائقين المتاحين حول نقطة، ويرتبهم حسب الأولوية."""
    radius = settings.get_int("dispatch.radius_meters", 5000)
    max_offers = settings.get_int("dispatch.max_offers_per_trip", 10)

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT * FROM find_nearby_drivers(%s, %s, %s, %s, %s)",
            (pickup_lat, pickup_lng, radius, max_offers * 2, car_type),
        )
        rows = cur.fetchall()

    if not rows:
        return []

    candidates = [
        {
            "driver_id": str(r["driver_id"]),
            "full_name": r["full_name"],
            "car_model": r["car_model"],
            "car_plate": r["car_plate"],
            "car_color": r.get("car_color"),
            "car_type": r.get("car_type", "sedan"),
            "rating_avg": float(r["rating_avg"]),
            "distance_meters": float(r["distance_meters"]),
            "lat": float(r["lat"]),
            "lng": float(r["lng"]),
        }
        for r in rows
    ]

    ranked = priority_service.rank_drivers_for_trip(
        pickup_lat, pickup_lng, candidates,
    )

    return ranked[:max_offers]


# ===== Create offers for a trip =====
def create_offers_for_trip(trip_id: str, candidates: list[dict]) -> list[dict]:
    """
    ينشئ صفوف driver_offers لكل سائق.
    يرجع قائمة العروض المنشأة (مع info).
    """
    if not candidates:
        return []

    timeout_sec = settings.get_int("dispatch.driver_accept_timeout_seconds", 20)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_sec)

    created = []
    with db_cursor(dict_cursor=True) as cur:
        for c in candidates:
            try:
                cur.execute(
                    """
                    INSERT INTO driver_offers
                        (trip_id, driver_id, expires_at, priority_score, distance_meters)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (trip_id, driver_id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        trip_id,
                        c["driver_id"],
                        expires_at,
                        c["priority_score"],
                        int(c["distance_meters"]),
                    ),
                )
                row = cur.fetchone()
                if row:
                    created.append({
                        "offer_id": str(row["id"]),
                        "driver_id": c["driver_id"],
                        "driver_name": c.get("full_name"),
                        "priority_score": c["priority_score"],
                        "distance_meters": c["distance_meters"],
                        "expires_at": expires_at.isoformat(),
                    })
            except Exception as e:
                logger.exception(f"create_offer failed for driver {c['driver_id']}: {e}")

    logger.info(f"Created {len(created)} offers for trip {trip_id}")
    return created


# ===== Accept trip (atomic) =====
def try_accept_trip(trip_id: str, driver_id: str) -> dict:
    """
    محاولة قبول رحلة بشكل atomic (advisory lock).
    يرجع {success: bool, error: str?, trip: dict?}
    """
    conn = None
    try:
        from app.core.database import get_connection_tx
        conn = get_connection_tx()

        with conn.cursor() as cur:
            # 1) advisory lock على الرحلة
            cur.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s)) AS locked",
                (f"trip:{trip_id}",),
            )
            locked = cur.fetchone()[0]

            if not locked:
                return {"success": False, "error": "race_condition"}

            try:
                # 2) تحقق من الرحلة
                cur.execute(
                    """
                    SELECT id, rider_id, driver_id, status, requested_at
                    FROM trips WHERE id = %s FOR UPDATE
                    """,
                    (trip_id,),
                )
                trip = cur.fetchone()

                if not trip:
                    return {"success": False, "error": "trip_not_found"}

                # row indices: 0=id, 1=rider_id, 2=driver_id, 3=status, 4=requested_at
                if trip[3] != "searching":
                    return {"success": False, "error": "trip_not_searching"}

                # 3) تحقق من العرض
                cur.execute(
                    """
                    SELECT id, response, expires_at
                    FROM driver_offers
                    WHERE trip_id = %s AND driver_id = %s
                    """,
                    (trip_id, driver_id),
                )
                offer = cur.fetchone()

                if not offer:
                    return {"success": False, "error": "no_offer"}

                # offer: 0=id, 1=response, 2=expires_at
                if offer[1] != "pending":
                    return {"success": False, "error": f"offer_{offer[1]}"}

                now = datetime.now(timezone.utc)
                if offer[2] and offer[2] < now:
                    return {"success": False, "error": "offer_expired"}

                # 4) خد idle_before_seconds
                cur.execute(
                    """
                    SELECT last_trip_completed_at FROM driver_priority_stats
                    WHERE driver_id = %s
                    """,
                    (driver_id,),
                )
                stats = cur.fetchone()
                idle_before = None
                if stats and stats[0]:
                    last = stats[0]
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    idle_before = int((now - last).total_seconds())

                # 5) تحديث الرحلة
                waiting_sec = int((now - trip[4]).total_seconds()) if trip[4] else None

                cur.execute(
                    """
                    UPDATE trips
                    SET driver_id = %s,
                        status = 'accepted',
                        accepted_at = NOW(),
                        waiting_for_driver_seconds = %s,
                        driver_idle_before_seconds = %s
                    WHERE id = %s
                    """,
                    (driver_id, waiting_sec, idle_before, trip_id),
                )

                # 6) تحديث العرض الحالي
                cur.execute(
                    """
                    UPDATE driver_offers
                    SET response = 'accepted', responded_at = NOW()
                    WHERE id = %s
                    """,
                    (offer[0],),
                )

                # 7) إلغاء العروض التانية
                cur.execute(
                    """
                    UPDATE driver_offers
                    SET response = 'expired', responded_at = NOW()
                    WHERE trip_id = %s AND id <> %s AND response = 'pending'
                    """,
                    (trip_id, offer[0]),
                )

                # 8) تحديث السائق
                cur.execute(
                    """
                    UPDATE drivers
                    SET availability_status = 'on_trip',
                        availability_changed_at = NOW()
                    WHERE user_id = %s
                    """,
                    (driver_id,),
                )

                conn.commit()
                return {
                    "success": True,
                    "trip": {
                        "id": str(trip[0]),
                        "rider_id": str(trip[1]),
                    },
                }
            finally:
                # release lock
                cur.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))",
                    (f"trip:{trip_id}",),
                )
    except Exception as e:
        logger.exception(f"try_accept_trip failed: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            conn.close()


# ===== Expire stale offers & trips =====
def expire_stale_data() -> dict:
    """
    يعلّم العروض المنتهية expired، والرحلات المنتهية expired.
    للاستخدام في background task.
    """
    offers_expired = 0
    trips_expired = 0

    try:
        with db_cursor() as cur:
            # 1) العروض
            cur.execute(
                """
                UPDATE driver_offers
                SET response = 'expired', responded_at = NOW()
                WHERE response = 'pending' AND expires_at IS NOT NULL AND expires_at < NOW()
                """
            )
            offers_expired = cur.rowcount

            # 2) الرحلات
            trip_timeout = settings.get_int("dispatch.trip_timeout_seconds", 300)
            cur.execute(
                """
                UPDATE trips
                SET status = 'expired'
                WHERE status = 'searching'
                  AND requested_at < NOW() - INTERVAL '%s seconds'
                """,
                (trip_timeout,),
            )
            trips_expired = cur.rowcount
    except Exception as e:
        logger.exception(f"expire_stale_data failed: {e}")

    return {"offers_expired": offers_expired, "trips_expired": trips_expired}


# ===== Broadcast expired events =====
def expire_and_notify():
    """
    يعلّم العروض/الرحلات المنتهية + يبث WS.
    """
    import asyncio
    offers_expired = 0
    trips_expired = 0
    expired_offers_data = []  # (driver_id, trip_id)
    expired_trips_data = []

    try:
        with db_cursor(dict_cursor=True) as cur:
            # 1) جلب العروض المنتهية قبل التحديث
            cur.execute(
                """
                SELECT id, driver_id, trip_id FROM driver_offers
                WHERE response = 'pending' AND expires_at IS NOT NULL AND expires_at < NOW()
                """
            )
            expired_offers_data = [
                (str(r["driver_id"]), str(r["trip_id"])) for r in cur.fetchall()
            ]

            cur.execute(
                """
                UPDATE driver_offers
                SET response = 'expired', responded_at = NOW()
                WHERE response = 'pending' AND expires_at IS NOT NULL AND expires_at < NOW()
                """
            )
            offers_expired = cur.rowcount

            # 2) الرحلات
            trip_timeout = settings.get_int("dispatch.trip_timeout_seconds", 300)

            cur.execute(
                """
                SELECT id FROM trips
                WHERE status = 'searching'
                  AND requested_at < NOW() - INTERVAL '%s seconds'
                """,
                (trip_timeout,),
            )
            expired_trips_data = [str(r["id"]) for r in cur.fetchall()]

            cur.execute(
                """
                UPDATE trips
                SET status = 'expired'
                WHERE status = 'searching'
                  AND requested_at < NOW() - INTERVAL '%s seconds'
                """,
                (trip_timeout,),
            )
            trips_expired = cur.rowcount

    except Exception as e:
        logger.exception(f"expire_and_notify failed: {e}")

    # Broadcasts
    if expired_offers_data or expired_trips_data:
        import asyncio
        from app.services import ws_notify

        async def _do():
            try:
                # لكل سائق عنده عرض expired
                for driver_id, trip_id in expired_offers_data:
                    await ws_notify.notify_offer_expired(driver_id, trip_id)

                # لكل رحلة expired
                for trip_id in expired_trips_data:
                    await ws_notify.notify_trip_status(trip_id, "expired")
            except Exception as e:
                logger.error(f"expire broadcast failed: {e}")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_do())
            else:
                loop.run_until_complete(_do())
        except Exception as e:
            logger.error(f"expire fire_and_forget failed: {e}")

    return {
        "offers_expired": offers_expired,
        "trips_expired": trips_expired,
    }