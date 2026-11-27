"""
Admin Reports Router — تقارير + CSV export
"""
import csv
import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.database import db_cursor
from app.core.deps import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# GET /trips — تقرير الرحلات
# ============================================================
@router.get("/trips", summary="تقرير الرحلات")
async def report_trips(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    status_filter: str | None = Query(None),
    format: str = Query("json", pattern="^(json|csv)$"),
    _admin: dict = Depends(require_role("admin")),
):
    where = ["1=1"]
    params: list = []

    if date_from:
        where.append("t.created_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        where.append("t.created_at <= %s::timestamptz")
        params.append(date_to)
    if status_filter:
        where.append("t.status = %s")
        params.append(status_filter)

    where_sql = " AND ".join(where)

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(f"""
            SELECT
                t.id::text AS trip_id,
                t.status,
                t.price_estimate,
                t.price_final,
                t.discount_amount,
                t.payment_method,
                t.distance_meters,
                t.requested_at,
                t.completed_at,
                t.cancelled_at,
                r.phone AS rider_phone,
                r.full_name AS rider_name,
                d.phone AS driver_phone,
                d.full_name AS driver_name
            FROM trips t
            JOIN users r ON r.id = t.rider_id
            LEFT JOIN users d ON d.id = t.driver_id
            WHERE {where_sql}
            ORDER BY t.created_at DESC
            LIMIT 5000
        """, params)
        rows = cur.fetchall()

    data = [
        {
            "trip_id": r["trip_id"],
            "status": r["status"],
            "price_estimate": float(r["price_estimate"]) if r["price_estimate"] else None,
            "price_final": float(r["price_final"]) if r["price_final"] else None,
            "discount_amount": float(r["discount_amount"]) if r["discount_amount"] else 0,
            "payment_method": r["payment_method"],
            "distance_meters": r["distance_meters"],
            "requested_at": r["requested_at"].isoformat() if r["requested_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "cancelled_at": r["cancelled_at"].isoformat() if r["cancelled_at"] else None,
            "rider_phone": r["rider_phone"],
            "rider_name": r["rider_name"],
            "driver_phone": r["driver_phone"],
            "driver_name": r["driver_name"],
        }
        for r in rows
    ]

    if format == "csv":
        return _to_csv(data, "trips_report")

    return {"data": data, "count": len(data)}


# ============================================================
# GET /financial — تقرير مالي
# ============================================================
@router.get("/financial", summary="تقرير مالي")
async def report_financial(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    format: str = Query("json", pattern="^(json|csv)$"),
    _admin: dict = Depends(require_role("admin")),
):
    where = ["1=1"]
    params: list = []

    if date_from:
        where.append("created_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        where.append("created_at <= %s::timestamptz")
        params.append(date_to)

    where_sql = " AND ".join(where)

    with db_cursor(dict_cursor=True) as cur:
        # Summary
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE status = 'completed') AS completed_trips,
                COALESCE(SUM(price_final) FILTER (WHERE status = 'completed'), 0) AS gross_revenue,
                COALESCE(SUM(discount_amount) FILTER (WHERE status = 'completed'), 0) AS total_discount,
                COUNT(*) AS total_trips
            FROM trips
            WHERE {where_sql}
        """, params)
        trips = cur.fetchone()

        # Commission
        cur.execute(f"""
            SELECT COALESCE(SUM(ABS(amount)), 0) AS total
            FROM wallet_transactions
            WHERE type = 'commission' AND {where_sql}
        """, params)
        commission = float(cur.fetchone()["total"])

        # Wallet transactions by type
        cur.execute(f"""
            SELECT type, COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total
            FROM wallet_transactions
            WHERE {where_sql}
            GROUP BY type
            ORDER BY type
        """, params)
        tx_summary = cur.fetchall()

    data = {
        "summary": {
            "completed_trips": trips["completed_trips"],
            "total_trips": trips["total_trips"],
            "gross_revenue": float(trips["gross_revenue"]),
            "total_discount": float(trips["total_discount"]),
            "commission": commission,
            "net_revenue": float(trips["gross_revenue"]) - commission,
        },
        "wallet_transactions": [
            {
                "type": r["type"],
                "count": r["count"],
                "total": float(r["total"]),
            }
            for r in tx_summary
        ],
    }

    if format == "csv":
        flat = [{"metric": k, "value": v} for k, v in data["summary"].items()]
        return _to_csv(flat, "financial_report")

    return data


# ============================================================
# Helpers
# ============================================================
def _to_csv(data: list[dict], filename: str) -> StreamingResponse:
    if not data:
        return StreamingResponse(
            io.StringIO(""),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}_{datetime.now().strftime("%Y%m%d")}.csv"'},
    )