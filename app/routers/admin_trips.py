"""
Admin Trips Router
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import db_cursor
from app.core.deps import require_role
from app.models.trip import (
    AdminForceCancelRequest,
    AdminReassignRequest,
    TripListResponse,
    TripListItem,
)
from app.services import ws_notify

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# Helper: fire & forget
# ============================================================
def _fire_and_forget(coro):
    """يشغّل coroutine في الخلفية بدون انتظار."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(coro)
        else:
            loop.run_until_complete(coro)
    except Exception as e:
        logger.error(f"fire_and_forget failed: {e}")


# ============================================================
# LIST
# ============================================================
@router.get("", response_model=TripListResponse, summary="كل الرحلات")
async def list_trips(
    status_filter: str | None = Query(None),
    rider_id: str | None = Query(None),
    driver_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    where = "1=1"
    params: list = []

    if status_filter:
        where += " AND status = %s"
        params.append(status_filter)
    if rider_id:
        where += " AND rider_id = %s"
        params.append(rider_id)
    if driver_id:
        where += " AND driver_id = %s"
        params.append(driver_id)

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"""
            SELECT id, status, rider_id, driver_id, pickup_address,
                   dropoff_address, price_estimate, price_final,
                   requested_at, completed_at
            FROM trips WHERE {where}
            ORDER BY requested_at DESC LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

        cur.execute(f"SELECT COUNT(*) AS c FROM trips WHERE {where}", params)
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


# ============================================================
# REASSIGN
# ============================================================
@router.post("/{trip_id}/reassign", summary="تحويل الرحلة لسائق آخر")
async def reassign(
    trip_id: str,
    data: AdminReassignRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT status, driver_id FROM trips WHERE id = %s",
            (trip_id,),
        )
        trip = cur.fetchone()

        if not trip:
            raise HTTPException(status_code=404, detail="الرحلة غير موجودة")

        if trip["status"] not in ("accepted", "arrived", "ongoing"):
            raise HTTPException(
                status_code=400,
                detail=f"ما يمكن تحويل رحلة بحالة '{trip['status']}'",
            )

        # تحقق من السائق الجديد
        cur.execute(
            "SELECT account_status, availability_status FROM drivers WHERE user_id = %s",
            (data.new_driver_id,),
        )
        new_drv = cur.fetchone()

        if not new_drv:
            raise HTTPException(status_code=404, detail="السائق الجديد غير موجود")
        if new_drv["account_status"] != "approved":
            raise HTTPException(status_code=400, detail="السائق غير موافق عليه")
        if new_drv["availability_status"] == "on_trip":
            raise HTTPException(status_code=400, detail="السائق مشغول برحلة")

        old_driver = str(trip["driver_id"]) if trip["driver_id"] else None

        # حرر السائق القديم
        if old_driver:
            cur.execute(
                """
                UPDATE drivers
                SET availability_status = 'online',
                    availability_changed_at = NOW()
                WHERE user_id = %s
                """,
                (old_driver,),
            )

        # اربط الجديد
        cur.execute(
            """
            UPDATE trips
            SET driver_id = %s, status = 'accepted'
            WHERE id = %s
            """,
            (data.new_driver_id, trip_id),
        )

        cur.execute(
            """
            UPDATE drivers
            SET availability_status = 'on_trip',
                availability_changed_at = NOW()
            WHERE user_id = %s
            """,
            (data.new_driver_id,),
        )

        # سجل
        cur.execute(
            """
            INSERT INTO admin_actions (admin_id, target_type, target_id, action, note)
            VALUES (%s, 'trip', %s, 'reassign', %s)
            """,
            (admin["sub"], trip_id, data.reason or f"تحويل إلى {data.new_driver_id}"),
        )

    # WS broadcast
    _fire_and_forget(ws_notify.notify_trip_status(
        trip_id=trip_id,
        status="accepted",
        extra={
            "reassigned": True,
            "new_driver_id": data.new_driver_id,
            "old_driver_id": old_driver,
        },
    ))

    return {"status": "success", "new_driver_id": data.new_driver_id}


# ============================================================
# FORCE CANCEL
# ============================================================
@router.post("/{trip_id}/force-cancel", summary="إلغاء قسري")
async def force_cancel(
    trip_id: str,
    data: AdminForceCancelRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT status, driver_id FROM trips WHERE id = %s",
            (trip_id,),
        )
        trip = cur.fetchone()

        if not trip:
            raise HTTPException(status_code=404, detail="الرحلة غير موجودة")

        if trip["status"] in ("completed", "cancelled", "expired"):
            raise HTTPException(
                status_code=400,
                detail=f"الرحلة '{trip['status']}' — ما يمكن إلغاؤها",
            )

        cur.execute(
            """
            UPDATE trips
            SET status = 'cancelled',
                cancelled_at = NOW(),
                cancelled_by = %s,
                cancellation_reason_text = %s
            WHERE id = %s
            """,
            (admin["sub"], data.reason, trip_id),
        )

        if trip["driver_id"]:
            cur.execute(
                """
                UPDATE drivers
                SET availability_status = 'online',
                    availability_changed_at = NOW()
                WHERE user_id = %s
                """,
                (str(trip["driver_id"]),),
            )

        cur.execute(
            """
            INSERT INTO admin_actions (admin_id, target_type, target_id, action, note)
            VALUES (%s, 'trip', %s, 'force_cancel', %s)
            """,
            (admin["sub"], trip_id, data.reason),
        )

    # WS broadcast
    _fire_and_forget(ws_notify.notify_trip_cancelled(
        trip_id=trip_id,
        reason=data.reason,
        by="admin",
    ))

    return {"status": "success", "trip_id": trip_id}