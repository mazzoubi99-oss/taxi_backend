"""
Trip service — state machine + business logic
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.core.database import db_cursor
from app.services import dispatch, pricing, settings
from app.services import promo as promo_service
from app.services import wallet as wallet_service
from app.services import ws_notify

logger = logging.getLogger(__name__)


# ============================================================
# REQUEST
# ============================================================
def create_trip(
    rider_id: str,
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
    pickup_address: Optional[str] = None,
    dropoff_address: Optional[str] = None,
    car_type: Optional[str] = None,
    payment_method: str = "cash",
    promo_code: Optional[str] = None,
    rider_note: Optional[str] = None,
    city: Optional[str] = None,
    estimate: Optional[dict] = None,
) -> dict:
    """ينشئ رحلة جديدة + يحسب السعر + يرسل العروض للسائقين."""
    # 1) تحقق من الرحلات النشطة للراكب
    max_active_rider = settings.get_int("trips.max_active_per_rider", 1)
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM trips
            WHERE rider_id = %s
              AND status IN ('searching','accepted','arrived','ongoing')
            """,
            (rider_id,),
        )
        active_count = cur.fetchone()["c"]

    if active_count >= max_active_rider:
        return {
            "success": False,
            "error": f"لديك {active_count} رحلة نشطة. لازم تخلصها قبل طلب رحلة جديدة.",
            "error_code": "max_active_trips",
        }

    # 2) حساب السعر
    estimate = estimate or pricing.estimate_trip(
        pickup_lat, pickup_lng, dropoff_lat, dropoff_lng, city=city, car_type=car_type,
    )
    distance_m = estimate["distance_meters"]
    duration_s = estimate["duration_seconds"]
    price_estimate = estimate["price"]
    breakdown = {
        **estimate["breakdown"],
        "car_type": car_type,
        "city": city,
        "route": estimate["route"],
    }

    # 3) promo
    promo_id = None
    discount_amount = 0.0
    final_price = price_estimate

    if promo_code:
        pv = promo_service.validate_promo(
            code=promo_code,
            user_id=rider_id,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            trip_price=price_estimate,
            car_type=car_type,
        )
        if pv["is_valid"]:
            promo_id = pv.get("promo_id")
            discount_amount = pv.get("discount_amount", 0.0)
            final_price = pv.get("final_price", price_estimate)
        else:
            return {
                "success": False,
                "error": pv.get("error_message", "كود خصم غير صالح"),
                "error_code": "invalid_promo",
            }

    # 4) start_code
    start_code = dispatch.generate_start_code()

    # 5) إنشاء الرحلة
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            INSERT INTO trips (
                rider_id, pickup_lat, pickup_lng, pickup_address,
                pickup_location,
                dropoff_lat, dropoff_lng, dropoff_address,
                dropoff_location,
                distance_meters, duration_seconds,
                price_estimate, payment_method,
                price_breakdown,
                promo_code_id, discount_amount,
                start_code,
                rider_note
            ) VALUES (
                %s, %s, %s, %s,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                %s, %s, %s,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                %s, %s,
                %s, %s,
                %s::jsonb,
                %s, %s,
                %s,
                %s
            )
            RETURNING id, requested_at
            """,
            (
                rider_id, pickup_lat, pickup_lng, pickup_address,
                pickup_lng, pickup_lat,
                dropoff_lat, dropoff_lng, dropoff_address,
                dropoff_lng, dropoff_lat,
                int(distance_m), duration_s,
                price_estimate, payment_method,
                _json_dumps(breakdown),
                promo_id, discount_amount,
                start_code,
                rider_note,
            ),
        )
        trip_row = cur.fetchone()

    trip_id = str(trip_row["id"])

    # 6) dispatch
    candidates = dispatch.find_and_rank_drivers(
        pickup_lat, pickup_lng, car_type=car_type,
    )
    offers = dispatch.create_offers_for_trip(trip_id, candidates)

    # 7) إشعارات DB
    if offers:
        try:
            from app.services import notifications as notif
            for offer in offers:
                notif.notify_driver_new_trip(
                    driver_id=offer["driver_id"],
                    trip_id=trip_id,
                    pickup_address=pickup_address,
                    price=price_estimate,
                    distance_to_pickup=offer["distance_meters"],
                )
        except Exception as e:
            logger.error(f"notify drivers failed: {e}")

    # 8) WS broadcasts (بشكل async — fire & forget)
    _fire_and_forget_created(
        trip_id=trip_id,
        rider_id=rider_id,
        pickup_lat=pickup_lat,
        pickup_lng=pickup_lng,
        pickup_address=pickup_address,
        dropoff_lat=dropoff_lat,
        dropoff_lng=dropoff_lng,
        dropoff_address=dropoff_address,
        price_estimate=price_estimate,
        requested_at=trip_row["requested_at"].isoformat(),
        offers=offers,
    )

    return {
        "success": True,
        "trip_id": trip_id,
        "price_estimate": price_estimate,
        "final_price": final_price,
        "discount_amount": discount_amount,
        "distance_meters": int(distance_m),
        "duration_seconds": duration_s,
        "offers_count": len(offers),
        "start_code": start_code,
    }


def _fire_and_forget_created(
    trip_id: str,
    rider_id: str,
    pickup_lat: float, pickup_lng: float, pickup_address: Optional[str],
    dropoff_lat: float, dropoff_lng: float, dropoff_address: Optional[str],
    price_estimate: float,
    requested_at: str,
    offers: list[dict],
):
    """يبعت broadcasts للـ WS بعد إنشاء الرحلة."""
    import asyncio

    trip_data = {
        "id": trip_id,
        "rider_id": rider_id,
        "pickup": {"lat": pickup_lat, "lng": pickup_lng, "address": pickup_address},
        "dropoff": {"lat": dropoff_lat, "lng": dropoff_lng, "address": dropoff_address},
        "price_estimate": price_estimate,
        "requested_at": requested_at,
    }

    async def _do():
        try:
            # للأدمن
            await ws_notify.notify_trip_created(trip_id, trip_data)

            # لكل سائق عنده offer
            for offer in offers:
                await ws_notify.notify_driver_offer(
                    driver_id=offer["driver_id"],
                    trip_id=trip_id,
                    offer_data={
                        "pickup": trip_data["pickup"],
                        "dropoff": trip_data["dropoff"],
                        "price_estimate": price_estimate,
                        "distance_to_pickup_meters": offer["distance_meters"],
                        "priority_score": offer["priority_score"],
                        "expires_at": offer["expires_at"],
                        "requested_at": requested_at,
                    },
                )
        except Exception as e:
            logger.error(f"ws_notify created failed: {e}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_do())
        else:
            loop.run_until_complete(_do())
    except Exception as e:
        logger.error(f"fire_and_forget failed: {e}")


# ============================================================
# ACCEPT
# ============================================================
def accept_trip(trip_id: str, driver_id: str) -> dict:
    """السائق يقبل رحلة (atomic)."""
    result = dispatch.try_accept_trip(trip_id, driver_id)

    if not result["success"]:
        error_map = {
            "race_condition": "حدا سبقك على الرحلة",
            "trip_not_found": "الرحلة غير موجودة",
            "trip_not_searching": "الرحلة لم تعد متاحة",
            "no_offer": "ليس لديك عرض لهذه الرحلة",
            "offer_accepted": "قبلت هذه الرحلة مسبقاً",
            "offer_rejected": "رفضت هذه الرحلة",
            "offer_expired": "انتهت صلاحية العرض",
        }
        return {
            "success": False,
            "error": error_map.get(result["error"], result["error"]),
            "error_code": result["error"],
        }

    rider_id = result["trip"]["rider_id"]

    # جلب بيانات السائق
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT u.full_name, u.phone AS driver_phone,
                   d.car_model, d.car_plate, d.car_color, d.rating_avg
            FROM users u
            JOIN drivers d ON d.user_id = u.id
            WHERE u.id = %s
            """,
            (driver_id,),
        )
        drv = cur.fetchone()

    driver_data = {
        "id": driver_id,
        "name": drv["full_name"] if drv else None,
        "phone": drv["driver_phone"] if drv else None,
        "car_model": drv.get("car_model") if drv else None,
        "car_plate": drv.get("car_plate") if drv else None,
        "car_color": drv.get("car_color") if drv else None,
        "rating": float(drv["rating_avg"]) if drv and drv.get("rating_avg") else None,
    }

    # إشعارات DB
    try:
        from app.services import notifications as notif
        notif.notify_rider_driver_accepted(rider_id, trip_id, driver_data["name"] or "")
        notif.notify_driver_trip_accepted(driver_id, trip_id)
    except Exception as e:
        logger.error(f"accept notifications failed: {e}")

    # WS broadcasts
    _fire_and_forget_accepted(trip_id, rider_id, driver_id, driver_data)

    return {
        "success": True,
        "trip_id": trip_id,
        "status": "accepted",
    }


def _fire_and_forget_accepted(trip_id, rider_id, driver_id, driver_data):
    import asyncio
    async def _do():
        try:
            await ws_notify.notify_trip_accepted(trip_id, driver_data, rider_id, driver_id)
        except Exception as e:
            logger.error(f"ws accepted failed: {e}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_do())
        else:
            loop.run_until_complete(_do())
    except Exception as e:
        logger.error(f"fire_and_forget_accepted failed: {e}")


# ============================================================
# REJECT
# ============================================================
def reject_trip(
    trip_id: str,
    driver_id: str,
    reason_id: Optional[str] = None,
    reason_text: Optional[str] = None,
) -> dict:
    """السائق يرفض عرض رحلة."""
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT status FROM trips WHERE id = %s AND driver_id IS NULL",
            (trip_id,),
        )
        trip = cur.fetchone()

        if not trip:
            return {"success": False, "error": "الرحلة غير موجودة أو تم قبولها"}

        if trip["status"] != "searching":
            return {"success": False, "error": "الرحلة لم تعد متاحة"}

        cur.execute(
            "SELECT id, response FROM driver_offers WHERE trip_id = %s AND driver_id = %s",
            (trip_id, driver_id),
        )
        offer = cur.fetchone()

        if not offer or offer["response"] != "pending":
            return {"success": False, "error": "لا يوجد عرض نشط"}

        cur.execute(
            """
            UPDATE driver_offers
            SET response = 'rejected', responded_at = NOW(), rejection_reason_id = %s
            WHERE id = %s
            """,
            (reason_id, offer["id"]),
        )

        counts = True
        if reason_id:
            cur.execute(
                "SELECT counts_as_rejection FROM cancellation_reasons WHERE id = %s",
                (reason_id,),
            )
            reason_row = cur.fetchone()
            if reason_row and not reason_row["counts_as_rejection"]:
                counts = False

        if not counts:
            cur.execute(
                """
                UPDATE driver_priority_stats
                SET rejected_offers = GREATEST(rejected_offers - 1, 0),
                    total_offers = GREATEST(total_offers - 1, 0)
                WHERE driver_id = %s
                """,
                (driver_id,),
            )

    return {
        "success": True,
        "trip_id": trip_id,
        "response": "rejected",
        "counted_as_rejection": counts,
    }


# ============================================================
# ARRIVE
# ============================================================
def mark_arrived(trip_id: str, driver_id: str) -> dict:
    """السائق وصل لنقطة الراكب."""
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT status, driver_id, accepted_at, rider_id FROM trips WHERE id = %s",
            (trip_id,),
        )
        trip = cur.fetchone()

        if not trip:
            return {"success": False, "error": "الرحلة غير موجودة"}
        if str(trip["driver_id"]) != driver_id:
            return {"success": False, "error": "هذه الرحلة ليست لك"}
        if trip["status"] != "accepted":
            return {"success": False, "error": f"حالة الرحلة '{trip['status']}' — لازم accepted"}

        now = datetime.now(timezone.utc)
        arrival_sec = int((now - trip["accepted_at"]).total_seconds()) if trip["accepted_at"] else None

        cur.execute(
            """
            UPDATE trips
            SET status = 'arrived', arrived_at = NOW(), driver_arrival_seconds = %s
            WHERE id = %s
            """,
            (arrival_sec, trip_id),
        )
        rider_id = str(trip["rider_id"])

    try:
        from app.services import notifications as notif
        notif.notify_rider_driver_arrived(rider_id, trip_id)
    except Exception as e:
        logger.error(f"arrive notification failed: {e}")

    _fire_and_forget_status(trip_id, "arrived")

    return {"success": True, "trip_id": trip_id, "status": "arrived"}


# ============================================================
# START
# ============================================================
def start_trip(trip_id: str, driver_id: str, code: Optional[str] = None) -> dict:
    """بدء الرحلة (مع تحقق من start_code إن مفعّل)."""
    code_enabled = settings.get_bool("trips.start_code_enabled", True)

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT status, driver_id, rider_id, start_code, start_code_attempts,
                   start_code_locked_until
            FROM trips WHERE id = %s
            """,
            (trip_id,),
        )
        trip = cur.fetchone()

        if not trip:
            return {"success": False, "error": "الرحلة غير موجودة"}
        if str(trip["driver_id"]) != driver_id:
            return {"success": False, "error": "هذه الرحلة ليست لك"}
        if trip["status"] not in ("arrived", "accepted"):
            return {"success": False, "error": f"حالة الرحلة '{trip['status']}'"}

        if code_enabled and trip["start_code"]:
            if trip["start_code_locked_until"]:
                now = datetime.now(timezone.utc)
                lock_until = trip["start_code_locked_until"]
                if lock_until.tzinfo is None:
                    lock_until = lock_until.replace(tzinfo=timezone.utc)
                if now < lock_until:
                    remaining = int((lock_until - now).total_seconds())
                    return {
                        "success": False,
                        "error": f"الكود مقفول. جرّب بعد {remaining} ثانية",
                        "locked_seconds": remaining,
                    }

            if not code or code != trip["start_code"]:
                attempts = (trip["start_code_attempts"] or 0) + 1
                max_attempts = settings.get_int("trips.start_code_max_attempts", 3)
                lock_minutes = settings.get_int("trips.start_code_lock_minutes", 5)

                lock_until = None
                if attempts >= max_attempts:
                    lock_until = datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)

                cur.execute(
                    "UPDATE trips SET start_code_attempts = %s, start_code_locked_until = %s WHERE id = %s",
                    (attempts, lock_until, trip_id),
                )

                remaining = max_attempts - attempts
                if remaining <= 0:
                    return {
                        "success": False,
                        "error": f"تجاوزت عدد المحاولات. الكود مقفول {lock_minutes} دقيقة",
                    }
                return {
                    "success": False,
                    "error": f"كود غير صحيح. باقي {remaining} محاولات",
                    "attempts_left": remaining,
                }

        cur.execute(
            """
            UPDATE trips
            SET status = 'ongoing',
                started_at = NOW(),
                start_code_verified = TRUE,
                start_code = NULL,
                start_code_locked_until = NULL
            WHERE id = %s
            """,
            (trip_id,),
        )
        rider_id = str(trip["rider_id"])

    try:
        from app.services import notifications as notif
        notif.notify_rider_trip_started(rider_id, trip_id)
    except Exception as e:
        logger.error(f"start notification failed: {e}")

    _fire_and_forget_status(trip_id, "ongoing")

    return {"success": True, "trip_id": trip_id, "status": "ongoing"}


# ============================================================
# COMPLETE
# ============================================================
def complete_trip(trip_id: str, driver_id: str) -> dict:
    """إنهاء الرحلة + حساب السعر النهائي + العمولة + promo."""
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT status, driver_id, rider_id, started_at, accepted_at,
                   pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
                   price_estimate, payment_method,
                   promo_code_id, discount_amount,
                   distance_meters, duration_seconds, price_breakdown
            FROM trips WHERE id = %s
            """,
            (trip_id,),
        )
        trip = cur.fetchone()

        if not trip:
            return {"success": False, "error": "الرحلة غير موجودة"}
        if str(trip["driver_id"]) != driver_id:
            return {"success": False, "error": "هذه الرحلة ليست لك"}
        if trip["status"] != "ongoing":
            return {"success": False, "error": f"حالة الرحلة '{trip['status']}'"}

        # المسافة/الوقت الفعليين من trip_locations
        cur.execute(
            """
            SELECT COUNT(*) AS c, MIN(recorded_at) AS first_at, MAX(recorded_at) AS last_at
            FROM trip_locations WHERE trip_id = %s AND recorded_at >= %s
            """,
            (trip_id, trip["started_at"]),
        )
        locs = cur.fetchone()

        actual_duration = None
        actual_distance = None

        if locs["c"] >= 2:
            actual_duration = int((locs["last_at"] - locs["first_at"]).total_seconds())
            cur.execute(
                """
                SELECT COALESCE(SUM(ST_Distance(lag_loc, location)), 0) AS total_m
                FROM (
                    SELECT location, LAG(location) OVER (ORDER BY recorded_at) AS lag_loc
                    FROM trip_locations WHERE trip_id = %s AND recorded_at >= %s
                ) sub
                WHERE lag_loc IS NOT NULL
                """,
                (trip_id, trip["started_at"]),
            )
            r = cur.fetchone()
            actual_distance = int(r["total_m"]) if r and r["total_m"] else None

        final_distance = actual_distance or trip["distance_meters"] or 0
        final_duration = actual_duration or trip["duration_seconds"] or 0

        original_pricing = trip["price_breakdown"] or {}
        breakdown = pricing.calculate_price(
            final_distance, final_duration,
            city=original_pricing.get("city"), car_type=original_pricing.get("car_type"),
        )
        price_final = breakdown["price"]

        # promo — إعادة حساب على السعر النهائي
        discount_amount = float(trip["discount_amount"] or 0)
        promo_id = trip["promo_code_id"]

        if promo_id:
            cur.execute(
                "SELECT discount_type, discount_value, max_discount_amount FROM promo_codes WHERE id = %s",
                (promo_id,),
            )
            p = cur.fetchone()
            if p:
                if p["discount_type"] == "percentage":
                    discount_amount = price_final * (float(p["discount_value"]) / 100.0)
                    if p["max_discount_amount"]:
                        discount_amount = min(discount_amount, float(p["max_discount_amount"]))
                else:
                    discount_amount = min(float(p["discount_value"]), price_final)

            promo_service.consume_promo(
                promo_id=str(promo_id),
                user_id=str(trip["rider_id"]),
                trip_id=trip_id,
                discount_amount=discount_amount,
            )

        final_charged = max(price_final - discount_amount, 0)

        # دفع
        payment_method = trip["payment_method"]
        wallet_deducted = 0.0
        if payment_method == "wallet":
            result = wallet_service.apply_transaction(
                user_id=str(trip["rider_id"]),
                type="trip_payment",
                amount=-final_charged,
                affects_balance=True,
                trip_id=trip_id,
                description=f"دفع رحلة {trip_id[:8]}",
                reference_type="trip",
                reference_id=trip_id,
            )
            if not result["success"]:
                return {
                    "success": False,
                    "error": f"فشل الدفع من المحفظة: {result.get('error_message')}",
                }
            wallet_deducted = final_charged

        # العمولة
        commission_result = wallet_service.charge_commission(
            user_id=driver_id,
            trip_id=trip_id,
            price=price_final,
        )
        if not commission_result["success"]:
            logger.warning(f"commission charge failed for trip {trip_id}: {commission_result}")

        # تحديث الرحلة
        cur.execute(
            """
            UPDATE trips
            SET status = 'completed',
                completed_at = NOW(),
                price_final = %s,
                discount_amount = %s,
                trip_duration_seconds = %s,
                trip_distance_meters = %s
            WHERE id = %s
            """,
            (price_final, discount_amount, final_duration, int(final_distance), trip_id),
        )

        cur.execute(
            """
            UPDATE drivers
            SET availability_status = 'online', availability_changed_at = NOW()
            WHERE user_id = %s
            """,
            (driver_id,),
        )
        rider_id = str(trip["rider_id"])

    try:
        from app.services import notifications as notif
        notif.notify_rider_trip_completed(rider_id, trip_id, price_final)
        notif.notify_driver_trip_completed(driver_id, trip_id, price_final)
    except Exception as e:
        logger.error(f"complete notifications failed: {e}")

    _fire_and_forget_completed(trip_id, price_final)

    return {
        "success": True,
        "trip_id": trip_id,
        "status": "completed",
        "price_final": price_final,
        "discount_amount": discount_amount,
        "final_charged": final_charged,
        "commission": commission_result.get("commission", 0),
        "wallet_deducted": wallet_deducted,
    }


# ============================================================
# CANCEL (by rider)
# ============================================================
def cancel_trip(
    trip_id: str,
    cancelled_by: str,
    reason_id: Optional[str] = None,
    reason_text: Optional[str] = None,
) -> dict:
    """الراكب يلغي رحلة."""
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT status, rider_id, driver_id FROM trips WHERE id = %s",
            (trip_id,),
        )
        trip = cur.fetchone()

        if not trip:
            return {"success": False, "error": "الرحلة غير موجودة"}

        if str(trip["rider_id"]) != cancelled_by:
            return {"success": False, "error": "هذه الرحلة ليست لك"}

        if trip["status"] not in ("searching", "accepted", "arrived"):
            return {"success": False, "error": f"ما يمكن إلغاء رحلة بحالة '{trip['status']}'"}

        if reason_id:
            cur.execute(
                "SELECT requires_note FROM cancellation_reasons WHERE id = %s",
                (reason_id,),
            )
            r = cur.fetchone()
            if r and r["requires_note"] and not reason_text:
                return {"success": False, "error": "هذا السبب يتطلب ملاحظة"}

        cur.execute(
            """
            UPDATE trips
            SET status = 'cancelled', cancelled_at = NOW(),
                cancelled_by = %s, cancellation_reason_id = %s,
                cancellation_reason_text = %s
            WHERE id = %s
            """,
            (cancelled_by, reason_id, reason_text, trip_id),
        )

        if trip["driver_id"] and trip["status"] in ("accepted", "arrived"):
            cur.execute(
                """
                UPDATE drivers
                SET availability_status = 'online', availability_changed_at = NOW()
                WHERE user_id = %s
                """,
                (str(trip["driver_id"]),),
            )

        cur.execute(
            """
            UPDATE driver_offers
            SET response = 'expired', responded_at = NOW()
            WHERE trip_id = %s AND response = 'pending'
            """,
            (trip_id,),
        )
        driver_id = str(trip["driver_id"]) if trip["driver_id"] else None

    try:
        from app.services import notifications as notif
        if driver_id:
            notif.notify_driver_trip_cancelled(driver_id, trip_id, "الراكب ألغى")
    except Exception as e:
        logger.error(f"cancel notification failed: {e}")

    _fire_and_forget_cancelled(trip_id, reason_text or "إلغاء الراكب", "rider", driver_id)

    return {"success": True, "trip_id": trip_id, "status": "cancelled"}


# ============================================================
# Fire & forget helpers
# ============================================================
def _fire_and_forget_status(trip_id: str, status: str):
    import asyncio
    async def _do():
        try:
            await ws_notify.notify_trip_status(trip_id, status)
        except Exception as e:
            logger.error(f"ws status failed: {e}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_do())
        else:
            loop.run_until_complete(_do())
    except Exception as e:
        logger.error(f"fire_and_forget_status failed: {e}")


def _fire_and_forget_completed(trip_id: str, price_final: float):
    import asyncio
    async def _do():
        try:
            await ws_notify.notify_trip_completed(trip_id, price_final)
        except Exception as e:
            logger.error(f"ws completed failed: {e}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_do())
        else:
            loop.run_until_complete(_do())
    except Exception as e:
        logger.error(f"fire_and_forget_completed failed: {e}")


def _fire_and_forget_cancelled(trip_id: str, reason: str, by: str, driver_id: Optional[str]):
    import asyncio
    async def _do():
        try:
            await ws_notify.notify_trip_cancelled(trip_id, reason, by, driver_id=driver_id)
        except Exception as e:
            logger.error(f"ws cancelled failed: {e}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_do())
        else:
            loop.run_until_complete(_do())
    except Exception as e:
        logger.error(f"fire_and_forget_cancelled failed: {e}")


# ============================================================
# Helpers
# ============================================================
def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)