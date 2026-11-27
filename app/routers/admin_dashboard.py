"""
Admin Dashboard Router — KPIs + Charts
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.database import db_cursor
from app.core.deps import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# GET /stats — KPIs
# ============================================================
@router.get("/stats", summary="إحصائيات Dashboard")
async def get_dashboard_stats(
    period: str = Query("today", pattern="^(today|week|month|all)$"),
    _admin: dict = Depends(require_role("admin")),
):
    """
    period: today / week / month / all
    """
    # تحديد الفترة
    if period == "today":
        since = "CURRENT_DATE"
    elif period == "week":
        since = "CURRENT_DATE - INTERVAL '7 days'"
    elif period == "month":
        since = "CURRENT_DATE - INTERVAL '30 days'"
    else:
        since = "NOW() - INTERVAL '10 years'"

    with db_cursor(dict_cursor=True) as cur:
        # 1) الرحلات
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status IN ('searching','accepted','arrived','ongoing')) AS active,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled,
                COUNT(*) FILTER (WHERE status = 'expired') AS expired,
                COALESCE(SUM(price_final) FILTER (WHERE status = 'completed'), 0) AS revenue,
                COALESCE(AVG(price_final) FILTER (WHERE status = 'completed'), 0) AS avg_price,
                COALESCE(AVG(driver_rating) FILTER (WHERE driver_rating IS NOT NULL), 0) AS avg_rating
            FROM trips
            WHERE created_at >= {since}
        """)
        trips = cur.fetchone()

        # 2) السائقين
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE account_status = 'pending') AS pending,
                COUNT(*) FILTER (WHERE account_status = 'approved') AS approved,
                COUNT(*) FILTER (WHERE account_status = 'rejected') AS rejected,
                COUNT(*) FILTER (WHERE account_status = 'banned') AS banned,
                COUNT(*) FILTER (WHERE availability_status = 'online' AND account_status = 'approved') AS online,
                COUNT(*) FILTER (WHERE availability_status = 'on_trip') AS on_trip
            FROM drivers
        """)
        drivers = cur.fetchone()

        # 3) الركاب
        cur.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'rider'")
        riders_count = cur.fetchone()["c"]

        # 4) الطلبات المعلقة
        cur.execute("SELECT COUNT(*) AS c FROM withdrawal_requests WHERE status = 'pending'")
        pending_withdrawals = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM deposit_requests WHERE status = 'pending'")
        pending_deposits = cur.fetchone()["c"]

        # 5) العمولات (المحفظة)
        cur.execute(f"""
            SELECT COALESCE(SUM(ABS(amount)), 0) AS total_commission
            FROM wallet_transactions
            WHERE type = 'commission' AND created_at >= {since}
        """)
        commission = cur.fetchone()["total_commission"]

    return {
        "period": period,
        "trips": {
            "completed": trips["completed"],
            "active": trips["active"],
            "cancelled": trips["cancelled"],
            "expired": trips["expired"],
            "revenue": float(trips["revenue"]),
            "avg_price": float(trips["avg_price"]),
            "avg_rating": float(trips["avg_rating"]),
        },
        "drivers": {
            "pending": drivers["pending"],
            "approved": drivers["approved"],
            "rejected": drivers["rejected"],
            "banned": drivers["banned"],
            "online": drivers["online"],
            "on_trip": drivers["on_trip"],
        },
        "riders": {
            "total": riders_count,
        },
        "pending": {
            "withdrawals": pending_withdrawals,
            "deposits": pending_deposits,
        },
        "commission": {
            "total": float(commission),
        },
    }


# ============================================================
# GET /charts — بيانات الرسوم البيانية
# ============================================================
@router.get("/charts", summary="بيانات رسوم Dashboard")
async def get_charts(_admin: dict = Depends(require_role("admin"))):
    with db_cursor(dict_cursor=True) as cur:
        # 1) رحلات آخر 7 أيام
        cur.execute("""
            SELECT
                DATE(created_at) AS day,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) AS total,
                COALESCE(SUM(price_final) FILTER (WHERE status = 'completed'), 0) AS revenue
            FROM trips
            WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY day ASC
        """)
        daily = cur.fetchall()

        # 2) توزيع حالات السائقين
        cur.execute("""
            SELECT account_status AS status, COUNT(*) AS count
            FROM drivers
            GROUP BY account_status
        """)
        driver_dist = cur.fetchall()

        # 3) أعلى 5 مناطق (حسب pickup_address)
        cur.execute("""
            SELECT
                COALESCE(pickup_address, 'غير محدد') AS area,
                COUNT(*) AS count
            FROM trips
            WHERE status = 'completed' AND created_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY pickup_address
            ORDER BY count DESC
            LIMIT 5
        """)
        top_areas = cur.fetchall()

        # 4) توزيع أنواع الدفع
        cur.execute("""
            SELECT payment_method AS method, COUNT(*) AS count
            FROM trips
            WHERE status = 'completed'
            GROUP BY payment_method
        """)
        payment_dist = cur.fetchall()

    return {
        "daily_trips": [
            {
                "day": r["day"].isoformat() if r["day"] else None,
                "completed": r["completed"],
                "total": r["total"],
                "revenue": float(r["revenue"]),
            }
            for r in daily
        ],
        "driver_status": [
            {"status": r["status"], "count": r["count"]} for r in driver_dist
        ],
        "top_areas": [
            {"area": r["area"], "count": r["count"]} for r in top_areas
        ],
        "payment_methods": [
            {"method": r["method"], "count": r["count"]} for r in payment_dist
        ],
    }


# ============================================================
# GET /activity — آخر الأحداث
# ============================================================
@router.get("/activity", summary="آخر الأحداث (feed)")
async def get_activity(
    limit: int = Query(20, ge=1, le=100),
    _admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(f"""
            SELECT
                'trip' AS type,
                t.id::text AS ref_id,
                t.status,
                t.price_final,
                t.created_at,
                r.full_name AS rider_name,
                d.full_name AS driver_name
            FROM trips t
            JOIN users r ON r.id = t.rider_id
            LEFT JOIN users d ON d.id = t.driver_id
            ORDER BY t.created_at DESC
            LIMIT {limit}
        """)
        trips = cur.fetchall()

    return [
        {
            "type": "trip",
            "ref_id": r["ref_id"],
            "status": r["status"],
            "price": float(r["price_final"]) if r["price_final"] else None,
            "rider_name": r["rider_name"],
            "driver_name": r["driver_name"],
            "at": r["created_at"].isoformat(),
        }
        for r in trips
    ]