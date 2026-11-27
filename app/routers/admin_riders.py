"""
Admin Riders Router
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import db_cursor
from app.core.deps import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# GET / — قائمة الركاب
# ============================================================
@router.get("", summary="قائمة الركاب")
async def list_riders(
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    where = "u.role = 'rider'"
    params: list = []

    if search:
        where += " AND (u.phone ILIKE %s OR u.full_name ILIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"""
            SELECT
                u.id, u.phone, u.full_name, u.email, u.is_active,
                u.created_at, u.last_login_at,
                (SELECT COUNT(*) FROM trips WHERE rider_id = u.id) AS total_trips,
                (SELECT COALESCE(SUM(price_final), 0) FROM trips
                 WHERE rider_id = u.id AND status = 'completed') AS total_spent,
                (SELECT balance FROM wallets WHERE user_id = u.id) AS wallet_balance
            FROM users u
            WHERE {where}
            ORDER BY u.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

        cur.execute(f"SELECT COUNT(*) AS c FROM users u WHERE {where}", params)
        total = cur.fetchone()["c"]

    return {
        "riders": [
            {
                "id": str(r["id"]),
                "phone": r["phone"],
                "full_name": r["full_name"],
                "email": r["email"],
                "is_active": r["is_active"],
                "created_at": r["created_at"].isoformat(),
                "last_login_at": r["last_login_at"].isoformat() if r["last_login_at"] else None,
                "total_trips": r["total_trips"],
                "total_spent": float(r["total_spent"]),
                "wallet_balance": float(r["wallet_balance"]) if r["wallet_balance"] else 0,
            }
            for r in rows
        ],
        "total": total,
    }


# ============================================================
# GET /{id} — تفاصيل راكب
# ============================================================
@router.get("/{rider_id}", summary="تفاصيل راكب")
async def get_rider(rider_id: str, _admin: dict = Depends(require_role("admin"))):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT
                u.id, u.phone, u.full_name, u.email, u.is_active,
                u.created_at, u.last_login_at,
                (SELECT balance FROM wallets WHERE user_id = u.id) AS wallet_balance
            FROM users u
            WHERE u.id = %s AND u.role = 'rider'
            """,
            (rider_id,),
        )
        rider = cur.fetchone()

        if not rider:
            raise HTTPException(status_code=404, detail="الراكب غير موجود")

        # آخر 10 رحلات
        cur.execute(
            """
            SELECT id, status, price_final, pickup_address, dropoff_address,
                   requested_at, completed_at
            FROM trips
            WHERE rider_id = %s
            ORDER BY requested_at DESC
            LIMIT 10
            """,
            (rider_id,),
        )
        trips = cur.fetchall()

    return {
        "id": str(rider["id"]),
        "phone": rider["phone"],
        "full_name": rider["full_name"],
        "email": rider["email"],
        "is_active": rider["is_active"],
        "created_at": rider["created_at"].isoformat(),
        "last_login_at": rider["last_login_at"].isoformat() if rider["last_login_at"] else None,
        "wallet_balance": float(rider["wallet_balance"]) if rider["wallet_balance"] else 0,
        "recent_trips": [
            {
                "id": str(t["id"]),
                "status": t["status"],
                "price_final": float(t["price_final"]) if t["price_final"] else None,
                "pickup_address": t["pickup_address"],
                "dropoff_address": t["dropoff_address"],
                "requested_at": t["requested_at"].isoformat(),
            }
            for t in trips
        ],
    }