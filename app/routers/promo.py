"""
Promo Router — للمستخدم
"""
import logging

from fastapi import APIRouter, Depends, Query

from app.core.database import db_cursor
from app.core.deps import get_current_user
from app.models.promo import (
    PromoUseResponse,
    PromoValidateRequest,
    PromoValidateResponse,
)
from app.services import promo as promo_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/validate",
    response_model=PromoValidateResponse,
    summary="التحقق من كود + حساب الخصم",
)
async def validate(data: PromoValidateRequest, user: dict = Depends(get_current_user)):
    result = promo_service.validate_promo(
        code=data.code,
        user_id=user["sub"],
        pickup_lat=data.pickup_lat,
        pickup_lng=data.pickup_lng,
        trip_price=data.trip_price,
        car_type=data.car_type,
    )
    return PromoValidateResponse(**result)


@router.get(
    "/my-uses",
    response_model=list[PromoUseResponse],
    summary="الكودات اللي استخدمتها",
)
async def my_uses(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT id, promo_code_id, user_id, trip_id, discount_amount, used_at
            FROM promo_code_uses
            WHERE user_id = %s
            ORDER BY used_at DESC
            LIMIT %s OFFSET %s
            """,
            (user["sub"], limit, offset),
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