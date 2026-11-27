"""
Admin Promo Router
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2 import errors

from app.core.database import db_cursor
from app.core.deps import require_role
from app.models.promo import (
    PromoCreateRequest,
    PromoListResponse,
    PromoResponse,
    PromoUpdateRequest,
    PromoUseResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _row_to_promo(row: dict) -> PromoResponse:
    return PromoResponse(
        id=str(row["id"]),
        code=row["code"],
        description=row.get("description"),
        discount_type=row["discount_type"],
        discount_value=float(row["discount_value"]),
        max_discount_amount=float(row["max_discount_amount"]) if row.get("max_discount_amount") else None,
        min_trip_amount=float(row["min_trip_amount"]),
        max_uses=row.get("max_uses"),
        max_uses_per_user=row.get("max_uses_per_user"),
        used_count=row["used_count"],
        valid_from=row["valid_from"].isoformat(),
        valid_until=row["valid_until"].isoformat() if row.get("valid_until") else None,
        is_active=row["is_active"],
        target_user_id=str(row["target_user_id"]) if row.get("target_user_id") else None,
        target_zone_id=str(row["target_zone_id"]) if row.get("target_zone_id") else None,
        applicable_car_types=row.get("applicable_car_types"),
        first_trip_only=row["first_trip_only"],
        created_at=row["created_at"].isoformat(),
    )


@router.post("", response_model=PromoResponse, status_code=201, summary="إنشاء كود")
async def create_promo(data: PromoCreateRequest, admin: dict = Depends(require_role("admin"))):
    try:
        with db_cursor(dict_cursor=True) as cur:
            cur.execute(
                """
                INSERT INTO promo_codes (
                    code, description, discount_type, discount_value, max_discount_amount,
                    min_trip_amount, max_uses, max_uses_per_user,
                    valid_from, valid_until, is_active,
                    target_user_id, target_zone_id, applicable_car_types, first_trip_only,
                    created_by
                )
                VALUES (
                    UPPER(%s), %s, %s, %s, %s,
                    %s, %s, %s,
                    COALESCE(%s::timestamptz, NOW()), %s::timestamptz, %s,
                    %s, %s, %s, %s,
                    %s
                )
                RETURNING *
                """,
                (
                    data.code, data.description, data.discount_type, data.discount_value,
                    data.max_discount_amount, data.min_trip_amount, data.max_uses,
                    data.max_uses_per_user, data.valid_from, data.valid_until,
                    data.is_active, data.target_user_id, data.target_zone_id,
                    data.applicable_car_types, data.first_trip_only, admin["sub"],
                ),
            )
            row = cur.fetchone()
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="الكود موجود بالفعل")
    except Exception as e:
        logger.exception(f"create_promo error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return _row_to_promo(row)


@router.get("", response_model=PromoListResponse, summary="كل الكودات")
async def list_promos(
    active_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    where = "1=1"
    if active_only:
        where = "is_active = TRUE"

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"SELECT * FROM promo_codes WHERE {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (limit, offset),
        )
        rows = cur.fetchall()
        cur.execute(f"SELECT COUNT(*) AS total FROM promo_codes WHERE {where}")
        total = cur.fetchone()["total"]

    return PromoListResponse(
        promos=[_row_to_promo(r) for r in rows],
        total=total,
    )


@router.get("/{promo_id}", response_model=PromoResponse, summary="تفاصيل كود")
async def get_promo(promo_id: str, _admin: dict = Depends(require_role("admin"))):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM promo_codes WHERE id = %s", (promo_id,))
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="الكود غير موجود")
    return _row_to_promo(row)


@router.put("/{promo_id}", response_model=PromoResponse, summary="تعديل كود")
async def update_promo(
    promo_id: str,
    data: PromoUpdateRequest,
    _admin: dict = Depends(require_role("admin")),
):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="لا يوجد بيانات للتحديث")

    set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
    values = list(updates.values()) + [promo_id]

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"UPDATE promo_codes SET {set_clause} WHERE id = %s RETURNING *",
            values,
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="الكود غير موجود")
    return _row_to_promo(row)


@router.delete("/{promo_id}", summary="حذف/تعطيل كود")
async def delete_promo(promo_id: str, _admin: dict = Depends(require_role("admin"))):
    with db_cursor() as cur:
        cur.execute("DELETE FROM promo_codes WHERE id = %s", (promo_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="الكود غير موجود")
    return {"status": "success"}


@router.get(
    "/{promo_id}/uses",
    response_model=list[PromoUseResponse],
    summary="من استخدم الكود",
)
async def promo_uses(
    promo_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT id, promo_code_id, user_id, trip_id, discount_amount, used_at
            FROM promo_code_uses
            WHERE promo_code_id = %s
            ORDER BY used_at DESC
            LIMIT %s OFFSET %s
            """,
            (promo_id, limit, offset),
        )
        rows = cur.fetchall()

    return [
        PromoUseResponse(
            id=str(r["id"]),
            promo_code_id=str(r["promo_code_id"]),
            user_id=str(r["user_id"]),
            trip_id=str(r["trip_id"]) if r.get("trip_id") else None,
            discount_amount=float(r["discount_amount"]),
            used_at=r["used_at"].isoformat(),
        )
        for r in rows
    ]