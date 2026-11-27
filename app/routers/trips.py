"""
Trips Router — للراكب والسائق
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import db_cursor
from app.core.deps import get_current_user, require_role
from app.models.trip import (
    AvailableTrip,
    TripAcceptResponse,
    TripCancelRequest,
    TripDetail,
    TripEstimateRequest,
    TripEstimateResponse,
    TripListItem,
    TripListResponse,
    TripRejectRequest,
    TripRequestCreate,
    TripRequestResponse,
    TripStartRequest,
)
from app.realtime.manager import manager
from app.services import pricing, trip_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# ESTIMATE (rider)
# ============================================================
@router.post(
    "/estimate",
    response_model=TripEstimateResponse,
    summary="تقدير السعر قبل الطلب",
)
async def estimate(
    data: TripEstimateRequest,
    _user: dict = Depends(get_current_user),
):
    result = pricing.estimate_trip(
        pickup_lat=data.pickup_lat,
        pickup_lng=data.pickup_lng,
        dropoff_lat=data.dropoff_lat,
        dropoff_lng=data.dropoff_lng,
        city=data.city,
        car_type=data.car_type,
    )
    return TripEstimateResponse(
        distance_meters=result["distance_meters"],
        duration_seconds=result["duration_seconds"],
        price=result["price"],
        breakdown=result["breakdown"],
    )


# ============================================================
# REQUEST (rider)
# ============================================================
@router.post(
    "/request",
    response_model=TripRequestResponse,
    summary="إنشاء رحلة جديدة",
)
async def request_trip(
    data: TripRequestCreate,
    user: dict = Depends(require_role("rider")),
):
    result = trip_service.create_trip(
        rider_id=user["sub"],
        pickup_lat=data.pickup_lat,
        pickup_lng=data.pickup_lng,
        dropoff_lat=data.dropoff_lat,
        dropoff_lng=data.dropoff_lng,
        pickup_address=data.pickup_address,
        dropoff_address=data.dropoff_address,
        car_type=data.car_type,
        payment_method=data.payment_method,
        promo_code=data.promo_code,
        rider_note=data.rider_note,
        city=data.city,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "فشل إنشاء الرحلة"),
        )

    return TripRequestResponse(**result)


# ============================================================
# GET TRIP (both)
# ============================================================
@router.get(
    "/{trip_id}",
    response_model=TripDetail,
    summary="تفاصيل رحلة",
)
async def get_trip(trip_id: str, user: dict = Depends(get_current_user)):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT t.*,
                   drv.full_name AS driver_name,
                   drv.phone AS driver_phone,
                   d.car_model, d.car_plate, d.car_color,
                   rdr.full_name AS rider_name,
                   rdr.phone AS rider_phone
            FROM trips t
            LEFT JOIN users drv ON drv.id = t.driver_id
            LEFT JOIN drivers d ON d.user_id = t.driver_id
            LEFT JOIN users rdr ON rdr.id = t.rider_id
            WHERE t.id = %s
            """,
            (trip_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="الرحلة غير موجودة")

    uid = user["sub"]
    if uid not in (str(row["rider_id"]), str(row["driver_id"])) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="غير مصرح")

    is_rider = uid == str(row["rider_id"])
    is_driver = uid == str(row["driver_id"])

    return TripDetail(
        id=str(row["id"]),
        status=row["status"],
        rider_id=str(row["rider_id"]),
        driver_id=str(row["driver_id"]) if row["driver_id"] else None,
        pickup_lat=float(row["pickup_lat"]),
        pickup_lng=float(row["pickup_lng"]),
        pickup_address=row.get("pickup_address"),
        dropoff_lat=float(row["dropoff_lat"]),
        dropoff_lng=float(row["dropoff_lng"]),
        dropoff_address=row.get("dropoff_address"),
        distance_meters=row.get("distance_meters"),
        duration_seconds=row.get("duration_seconds"),
        price_estimate=float(row["price_estimate"]) if row.get("price_estimate") else None,
        price_final=float(row["price_final"]) if row.get("price_final") else None,
        discount_amount=float(row["discount_amount"] or 0),
        payment_method=row["payment_method"],
        currency=row.get("currency", "SYP"),
        start_code=row.get("start_code") if is_rider else None,
        requested_at=row["requested_at"].isoformat(),
        accepted_at=row["accepted_at"].isoformat() if row.get("accepted_at") else None,
        arrived_at=row["arrived_at"].isoformat() if row.get("arrived_at") else None,
        started_at=row["started_at"].isoformat() if row.get("started_at") else None,
        completed_at=row["completed_at"].isoformat() if row.get("completed_at") else None,
        cancelled_at=row["cancelled_at"].isoformat() if row.get("cancelled_at") else None,
        cancellation_reason_id=str(row["cancellation_reason_id"]) if row.get("cancellation_reason_id") else None,
        cancellation_reason_text=row.get("cancellation_reason_text"),
        rider_rating=row.get("rider_rating"),
        driver_rating=row.get("driver_rating"),
        driver_name=row.get("driver_name"),
        driver_phone=row.get("driver_phone") if not is_rider else None,
        car_model=row.get("car_model"),
        car_plate=row.get("car_plate"),
        car_color=row.get("car_color"),
        rider_name=row.get("rider_name") if is_driver else None,
        rider_phone=row.get("rider_phone") if is_driver else None,
    )


# ============================================================
# MY TRIPS (rider)
# ============================================================
@router.get(
    "/my/rider",
    response_model=TripListResponse,
    summary="رحلاتي كراكب",
)
async def my_rider_trips(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_role("rider")),
):
    return _list_trips("rider_id", user["sub"], limit, offset)


# ============================================================
# MY TRIPS (driver)
# ============================================================
@router.get(
    "/my/driver",
    response_model=TripListResponse,
    summary="رحلاتي كسائق",
)
async def my_driver_trips(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_role("driver")),
):
    return _list_trips("driver_id", user["sub"], limit, offset)


# ============================================================
# AVAILABLE (driver)
# ============================================================
@router.get(
    "/available/list",
    response_model=list[AvailableTrip],
    summary="الرحلات المتاحة (للسائق)",
)
async def available_trips(user: dict = Depends(require_role("driver"))):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT t.id, t.pickup_lat, t.pickup_lng, t.pickup_address,
                   t.dropoff_lat, t.dropoff_lng, t.dropoff_address,
                   t.distance_meters, t.duration_seconds,
                   t.price_estimate, t.requested_at,
                   o.priority_score, o.distance_meters AS pickup_distance,
                   o.expires_at
            FROM trips t
            JOIN driver_offers o ON o.trip_id = t.id
            WHERE t.status = 'searching'
              AND o.driver_id = %s
              AND o.response = 'pending'
              AND o.expires_at > NOW()
            ORDER BY o.priority_score DESC NULLS LAST
            """,
            (user["sub"],),
        )
        rows = cur.fetchall()

    return [
        AvailableTrip(
            trip_id=str(r["id"]),
            pickup_lat=float(r["pickup_lat"]),
            pickup_lng=float(r["pickup_lng"]),
            pickup_address=r.get("pickup_address"),
            dropoff_lat=float(r["dropoff_lat"]),
            dropoff_lng=float(r["dropoff_lng"]),
            dropoff_address=r.get("dropoff_address"),
            distance_meters=r.get("distance_meters"),
            duration_seconds=r.get("duration_seconds"),
            price_estimate=float(r["price_estimate"]) if r.get("price_estimate") else None,
            pickup_distance_meters=r.get("pickup_distance"),
            priority_score=float(r["priority_score"]) if r.get("priority_score") else None,
            expires_at=r["expires_at"].isoformat() if r.get("expires_at") else None,
            requested_at=r["requested_at"].isoformat(),
        )
        for r in rows
    ]


# ============================================================
# ACCEPT (driver)
# ============================================================
@router.post(
    "/{trip_id}/accept",
    response_model=TripAcceptResponse,
    summary="قبول رحلة",
)
async def accept(trip_id: str, user: dict = Depends(require_role("driver"))):
    result = trip_service.accept_trip(trip_id, user["sub"])
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result.get("error", "فشل القبول"))
    return TripAcceptResponse(**result)


# ============================================================
# REJECT (driver)
# ============================================================
@router.post(
    "/{trip_id}/reject",
    summary="رفض رحلة",
)
async def reject(
    trip_id: str,
    data: TripRejectRequest,
    user: dict = Depends(require_role("driver")),
):
    result = trip_service.reject_trip(
        trip_id, user["sub"],
        reason_id=data.reason_id,
        reason_text=data.reason_text,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ============================================================
# ARRIVE (driver)
# ============================================================
@router.post(
    "/{trip_id}/arrive",
    summary="السائق وصل",
)
async def arrive(trip_id: str, user: dict = Depends(require_role("driver"))):
    result = trip_service.mark_arrived(trip_id, user["sub"])
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ============================================================
# START (driver)
# ============================================================
@router.post(
    "/{trip_id}/start",
    summary="بدء الرحلة (مع كود)",
)
async def start(
    trip_id: str,
    data: TripStartRequest,
    user: dict = Depends(require_role("driver")),
):
    result = trip_service.start_trip(trip_id, user["sub"], code=data.code)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ============================================================
# COMPLETE (driver)
# ============================================================
@router.post(
    "/{trip_id}/complete",
    summary="إنهاء الرحلة",
)
async def complete(trip_id: str, user: dict = Depends(require_role("driver"))):
    result = trip_service.complete_trip(trip_id, user["sub"])
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ============================================================
# CANCEL (rider)
# ============================================================
@router.post(
    "/{trip_id}/cancel",
    summary="إلغاء رحلة (راكب)",
)
async def cancel(
    trip_id: str,
    data: TripCancelRequest,
    user: dict = Depends(require_role("rider")),
):
    result = trip_service.cancel_trip(
        trip_id, user["sub"],
        reason_id=data.reason_id,
        reason_text=data.reason_text,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# ============================================================
# LOCATION UPDATE (HTTP fallback)
# ============================================================
@router.post(
    "/{trip_id}/location",
    summary="تحديث موقع السائق (HTTP بديل للـ WebSocket)",
)
async def update_trip_location(
    trip_id: str,
    body: dict,
    user: dict = Depends(require_role("driver")),
):
    """
    Body: {lat, lng, heading?, speed?}
    """
    try:
        lat = float(body["lat"])
        lng = float(body["lng"])
        heading = body.get("heading")
        speed = body.get("speed")
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="lat/lng مطلوبة")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    with db_cursor(dict_cursor=True) as cur:
        # تحقق
        cur.execute(
            "SELECT driver_id FROM trips WHERE id = %s",
            (trip_id,),
        )
        trip = cur.fetchone()

        if not trip or str(trip["driver_id"]) != user["sub"]:
            raise HTTPException(status_code=403, detail="غير مصرح")

        # سجل في trip_locations (كل 10s)
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
            if (now - last_at).total_seconds() < 10:
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
                (trip_id, user["sub"], lat, lng, lng, lat, heading, speed),
            )

        # حدّث آخر موقع
        cur.execute(
            "UPDATE trips SET last_driver_location = %s::jsonb WHERE id = %s",
            (json.dumps({
                "lat": lat, "lng": lng,
                "heading": heading, "speed": speed,
                "at": now_iso,
            }), trip_id),
        )

    # بث عبر WS
    try:
        await manager.broadcast(f"trip:{trip_id}", {
            "type": "driver_location",
            "trip_id": trip_id,
            "lat": lat,
            "lng": lng,
            "heading": heading,
            "speed": speed,
            "at": now_iso,
        })
    except Exception as e:
        logger.warning(f"WS broadcast failed: {e}")

    return {"status": "success", "lat": lat, "lng": lng}


# ============================================================
# Helpers
# ============================================================
def _list_trips(field: str, user_id: str, limit: int, offset: int) -> TripListResponse:
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"""
            SELECT id, status, rider_id, driver_id, pickup_address,
                   dropoff_address, price_estimate, price_final,
                   requested_at, completed_at
            FROM trips
            WHERE {field} = %s
            ORDER BY requested_at DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, limit, offset),
        )
        rows = cur.fetchall()

        cur.execute(f"SELECT COUNT(*) AS c FROM trips WHERE {field} = %s", (user_id,))
        total = cur.fetchone()["c"]

    return TripListResponse(
        trips=[
            TripListItem(
                id=str(r["id"]),
                status=r["status"],
                rider_id=str(r["rider_id"]),
                driver_id=str(r["driver_id"]) if r["driver_id"] else None,
                pickup_address=r.get("pickup_address"),
                dropoff_address=r.get("dropoff_address"),
                price_estimate=float(r["price_estimate"]) if r.get("price_estimate") else None,
                price_final=float(r["price_final"]) if r.get("price_final") else None,
                requested_at=r["requested_at"].isoformat(),
                completed_at=r["completed_at"].isoformat() if r.get("completed_at") else None,
            )
            for r in rows
        ],
        total=total,
    )


@router.post("/{trip_id}/rate", summary="تقييم الرحلة")
async def rate_trip(
    trip_id: str,
    body: dict,
    user: dict = Depends(require_role("rider")),
):
    stars = int(body.get("stars", 0))
    comment = body.get("comment")
    tags = body.get("tags", [])

    if stars < 1 or stars > 5:
        raise HTTPException(status_code=400, detail="التقييم 1-5")

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT driver_id, rider_id, status FROM trips WHERE id = %s",
            (trip_id,),
        )
        trip = cur.fetchone()

        if not trip:
            raise HTTPException(status_code=404, detail="الرحلة غير موجودة")
        if str(trip["rider_id"]) != user["sub"]:
            raise HTTPException(status_code=403, detail="غير مصرح")
        if trip["status"] != "completed":
            raise HTTPException(status_code=400, detail="الرحلة غير مكتملة")
        if not trip["driver_id"]:
            raise HTTPException(status_code=400, detail="لا يوجد سائق")

        # check duplicate
        cur.execute(
            "SELECT id FROM ratings WHERE trip_id = %s AND from_user_id = %s",
            (trip_id, user["sub"]),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="قيّمت هذه الرحلة مسبقاً")

        # insert rating
        cur.execute(
            """
            INSERT INTO ratings (trip_id, from_user_id, to_user_id, stars, comment, tags)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (trip_id, user["sub"], str(trip["driver_id"]), stars, comment, tags),
        )

        # update trip
        cur.execute(
            "UPDATE trips SET driver_rating = %s WHERE id = %s",
            (stars, trip_id),
        )

    return {"status": "success", "stars": stars}