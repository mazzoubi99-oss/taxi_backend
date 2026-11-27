"""
Promo code service — تحقق + حساب الخصم
"""
import logging
from typing import Optional

from app.core.database import db_cursor

logger = logging.getLogger(__name__)


def validate_promo(
    code: str,
    user_id: str,
    pickup_lat: float,
    pickup_lng: float,
    trip_price: float,
    car_type: Optional[str] = None,
) -> dict:
    """يتحقق من كود + يحسب الخصم."""
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT * FROM validate_promo_code(%s, %s, %s, %s, %s, %s)",
            (code, user_id, pickup_lat, pickup_lng, trip_price, car_type),
        )
        row = cur.fetchone()

    if not row:
        return {
            "is_valid": False,
            "error_message": "فشل التحقق من الكود",
            "discount_amount": 0,
            "final_price": trip_price,
        }

    return {
        "is_valid": row["is_valid"],
        "error_message": row.get("error_message"),
        "promo_id": str(row["promo_id"]) if row.get("promo_id") else None,
        "discount_type": row.get("discount_type"),
        "discount_value": float(row["discount_value"]) if row.get("discount_value") else None,
        "discount_amount": float(row["discount_amount"]) if row.get("discount_amount") else 0,
        "final_price": float(row["final_price"]) if row.get("final_price") else trip_price,
    }


def consume_promo(promo_id: str, user_id: str, trip_id: str, discount_amount: float) -> bool:
    """يزيد used_count + يسجل في promo_code_uses."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "UPDATE promo_codes SET used_count = used_count + 1 WHERE id = %s",
                (promo_id,),
            )
            cur.execute(
                """
                INSERT INTO promo_code_uses
                    (promo_code_id, user_id, trip_id, discount_amount)
                VALUES (%s, %s, %s, %s)
                """,
                (promo_id, user_id, trip_id, discount_amount),
            )
        return True
    except Exception as e:
        logger.exception(f"consume_promo error: {e}")
        return False