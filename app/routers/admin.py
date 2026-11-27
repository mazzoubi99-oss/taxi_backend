"""
Admin Router — إدارة السائقين
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import db_cursor
from app.core.deps import require_role
from app.models.admin import (
    AdminDocumentResponse,
    AdminDriverDetailResponse,
    AdminDriverListItem,
    AdminDriverListResponse,
    DriverActionRequest,
    DriverBanRequest,
    DriverRejectRequest,
)
from app.services import notifications as notif

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== Helpers =====
def _log_admin_action(
    cur,
    admin_id: str,
    target_type: str,
    target_id: str,
    action: str,
    note: str | None = None,
    metadata: dict | None = None,
):
    cur.execute(
        """
        INSERT INTO admin_actions
            (admin_id, target_type, target_id, action, note, metadata)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (admin_id, target_type, target_id, action, note, metadata),
    )


def _fetch_driver_row(cur, driver_id: str) -> dict | None:
    cur.execute(
        """
        SELECT
            d.user_id, d.car_model, d.car_plate, d.car_color, d.car_year, d.car_type,
            d.account_status, d.account_status_note, d.availability_status,
            d.current_lat, d.current_lng,
            d.rating_avg, d.rating_count, d.total_trips, d.wallet_balance,
            d.created_at,
            u.phone, u.full_name, u.email
        FROM drivers d
        JOIN users u ON u.id = d.user_id
        WHERE d.user_id = %s
        """,
        (driver_id,),
    )
    return cur.fetchone()


def _driver_row_to_item(row: dict) -> AdminDriverListItem:
    return AdminDriverListItem(
        user_id=str(row["user_id"]),
        phone=row["phone"],
        full_name=row["full_name"],
        car_model=row["car_model"],
        car_plate=row["car_plate"],
        car_type=row["car_type"],
        account_status=row["account_status"],
        availability_status=row["availability_status"],
        rating_avg=float(row["rating_avg"]),
        total_trips=row["total_trips"],
        created_at=row["created_at"].isoformat(),
    )


# ===== GET /drivers/pending =====
@router.get(
    "/drivers/pending",
    response_model=AdminDriverListResponse,
    summary="السائقين قيد الانتظار",
)
async def list_pending_drivers(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT
                d.user_id, d.car_model, d.car_plate, d.car_type,
                d.account_status, d.availability_status,
                d.rating_avg, d.total_trips, d.created_at,
                u.phone, u.full_name
            FROM drivers d
            JOIN users u ON u.id = d.user_id
            WHERE d.account_status = 'pending'
            ORDER BY d.created_at ASC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = cur.fetchall()

        cur.execute(
            "SELECT COUNT(*) AS total FROM drivers WHERE account_status = 'pending'"
        )
        total = cur.fetchone()["total"]

    return AdminDriverListResponse(
        drivers=[_driver_row_to_item(r) for r in rows],
        total=total,
    )


# ===== GET /drivers =====
@router.get("/drivers", response_model=AdminDriverListResponse, summary="كل السائقين")
async def list_drivers(
    status: str | None = Query(None, pattern="^(pending|approved|rejected|banned)$"),
    availability: str | None = Query(None, pattern="^(offline|online|on_trip)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    where = ["1=1"]
    params: list = []

    if status:
        where.append("d.account_status = %s")
        params.append(status)

    if availability:
        where.append("d.availability_status = %s")
        params.append(availability)

    where_sql = " AND ".join(where)

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"""
            SELECT
                d.user_id, d.car_model, d.car_plate, d.car_type,
                d.account_status, d.availability_status,
                d.rating_avg, d.total_trips, d.created_at,
                u.phone, u.full_name
            FROM drivers d
            JOIN users u ON u.id = d.user_id
            WHERE {where_sql}
            ORDER BY d.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

        cur.execute(
            f"SELECT COUNT(*) AS total FROM drivers d WHERE {where_sql}",
            params,
        )
        total = cur.fetchone()["total"]

    return AdminDriverListResponse(
        drivers=[_driver_row_to_item(r) for r in rows],
        total=total,
    )


# ===== GET /drivers/{id} =====
@router.get(
    "/drivers/{driver_id}",
    response_model=AdminDriverDetailResponse,
    summary="تفاصيل سائق + مستنداته (بدون صور)",
)
async def get_driver_detail(
    driver_id: str,
    _admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        row = _fetch_driver_row(cur, driver_id)
        if not row:
            raise HTTPException(status_code=404, detail="السائق غير موجود")

        cur.execute(
            """
            SELECT doc_type, mime_type, uploaded_at
            FROM driver_documents
            WHERE driver_id = %s
            ORDER BY doc_type
            """,
            (driver_id,),
        )
        docs = cur.fetchall()

    return AdminDriverDetailResponse(
        user_id=str(row["user_id"]),
        phone=row["phone"],
        full_name=row["full_name"],
        email=row.get("email"),
        car_model=row["car_model"],
        car_plate=row["car_plate"],
        car_color=row.get("car_color"),
        car_year=row.get("car_year"),
        car_type=row["car_type"],
        account_status=row["account_status"],
        account_status_note=row.get("account_status_note"),
        availability_status=row["availability_status"],
        current_lat=row.get("current_lat"),
        current_lng=row.get("current_lng"),
        wallet_balance=float(row["wallet_balance"]),
        rating_avg=float(row["rating_avg"]),
        rating_count=row["rating_count"],
        total_trips=row["total_trips"],
        created_at=row["created_at"].isoformat(),
        documents=[
            AdminDocumentResponse(
                doc_type=d["doc_type"],
                mime_type=d["mime_type"],
                uploaded_at=d["uploaded_at"].isoformat(),
            )
            for d in docs
        ],
    )


# ===== GET /drivers/{id}/documents/{type} =====
@router.get(
    "/drivers/{driver_id}/documents/{doc_type}",
    response_model=AdminDocumentResponse,
    summary="جلب صورة مستند للتحقق",
)
async def get_driver_document(
    driver_id: str,
    doc_type: str,
    _admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT doc_type, mime_type, uploaded_at, image_base64
            FROM driver_documents
            WHERE driver_id = %s AND doc_type = %s
            """,
            (driver_id, doc_type),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="المستند غير موجود")

    return AdminDocumentResponse(
        doc_type=row["doc_type"],
        mime_type=row["mime_type"],
        uploaded_at=row["uploaded_at"].isoformat(),
        image_base64=row["image_base64"],
    )


# ===== POST /drivers/{id}/approve =====
@router.post("/drivers/{driver_id}/approve", summary="موافقة على سائق")
async def approve_driver(
    driver_id: str,
    data: DriverActionRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        row = _fetch_driver_row(cur, driver_id)
        if not row:
            raise HTTPException(status_code=404, detail="السائق غير موجود")

        if row["account_status"] == "approved":
            raise HTTPException(status_code=409, detail="السائق موافق عليه مسبقاً")

        cur.execute(
            """
            UPDATE drivers
            SET account_status = 'approved',
                account_status_note = %s,
                approved_at = NOW(),
                approved_by = %s
            WHERE user_id = %s
            """,
            (data.note, admin["sub"], driver_id),
        )

        _log_admin_action(
            cur,
            admin["sub"],
            "driver",
            driver_id,
            "approve",
            note=data.note,
        )

    notif.notify_driver_approved(admin["sub"], driver_id)

    return {"status": "success", "account_status": "approved"}


# ===== POST /drivers/{id}/reject =====
@router.post("/drivers/{driver_id}/reject", summary="رفض سائق")
async def reject_driver(
    driver_id: str,
    data: DriverRejectRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        row = _fetch_driver_row(cur, driver_id)
        if not row:
            raise HTTPException(status_code=404, detail="السائق غير موجود")

        cur.execute(
            """
            UPDATE drivers
            SET account_status = 'rejected',
                account_status_note = %s
            WHERE user_id = %s
            """,
            (data.reason, driver_id),
        )

        _log_admin_action(
            cur,
            admin["sub"],
            "driver",
            driver_id,
            "reject",
            note=data.reason,
        )

    notif.notify_driver_rejected(admin["sub"], driver_id, data.reason)

    return {"status": "success", "account_status": "rejected"}


# ===== POST /drivers/{id}/ban =====
@router.post("/drivers/{driver_id}/ban", summary="حظر سائق")
async def ban_driver(
    driver_id: str,
    data: DriverBanRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        row = _fetch_driver_row(cur, driver_id)
        if not row:
            raise HTTPException(status_code=404, detail="السائق غير موجود")

        cur.execute(
            """
            UPDATE drivers
            SET account_status = 'banned',
                account_status_note = %s,
                availability_status = 'offline',
                availability_changed_at = NOW()
            WHERE user_id = %s
            """,
            (data.reason, driver_id),
        )

        _log_admin_action(
            cur,
            admin["sub"],
            "driver",
            driver_id,
            "ban",
            note=data.reason,
        )

    notif.notify_driver_banned(admin["sub"], driver_id, data.reason)

    return {"status": "success", "account_status": "banned"}


# ===== POST /drivers/{id}/unban =====
@router.post("/drivers/{driver_id}/unban", summary="رفع الحظر")
async def unban_driver(
    driver_id: str,
    data: DriverActionRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        row = _fetch_driver_row(cur, driver_id)
        if not row:
            raise HTTPException(status_code=404, detail="السائق غير موجود")

        if row["account_status"] != "banned":
            raise HTTPException(status_code=409, detail="السائق غير محظور")

        cur.execute(
            """
            UPDATE drivers
            SET account_status = 'pending',
                account_status_note = %s
            WHERE user_id = %s
            """,
            (data.note, driver_id),
        )

        _log_admin_action(
            cur,
            admin["sub"],
            "driver",
            driver_id,
            "unban",
            note=data.note,
        )

    notif.notify_driver_unbanned(admin["sub"], driver_id)

    return {"status": "success", "account_status": "pending"}

@router.get("/account-deletion-requests", summary="طلبات حذف الحساب")
def account_deletion_requests(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT user_id, requested_at
            FROM account_deletion_requests
            ORDER BY requested_at, user_id
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return cur.fetchall()
