"""
Pricing service — حساب المسافة والوقت والسعر
"""
import logging
import math
from typing import Optional

from app.core.database import db_cursor
from app.services import settings
from app.services.road_route import driving_route

logger = logging.getLogger(__name__)

EARTH_RADIUS_METERS = 6_371_000


# ===== Distance (Haversine) =====
def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """المسافة بين نقطتين بالأمتار (خط مستقيم)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_METERS * c


# ===== Duration estimate =====
def estimate_duration_seconds(distance_meters: float) -> int:
    """الوقت المتوقع بالثواني حسب سرعة متوسطة."""
    speed_kmh = settings.get_float("pricing.default_speed_kmh", 30.0)
    if speed_kmh <= 0:
        speed_kmh = 30.0
    speed_mps = speed_kmh * 1000 / 3600
    return max(1, int(distance_meters / speed_mps))


# ===== Pricing rule =====
def get_pricing_rule(city: Optional[str] = None,
                     car_type: Optional[str] = None) -> Optional[dict]:
    """
    يجيب قاعدة التسعير النشطة:
    - أولاً: (city, car_type)
    - ثانياً: (city, NULL) لو car_type محدد
    - ثالثاً: (NULL, car_type)
    - رابعاً: (NULL, NULL) — قاعدة عامة
    """
    car_type = car_type or "sedan"

    with db_cursor(dict_cursor=True) as cur:
        # 1) city + car_type
        if city:
            cur.execute(
                """
                SELECT * FROM pricing_rules
                WHERE is_active = TRUE
                  AND city = %s AND car_type = %s
                  AND (valid_until IS NULL OR valid_until > NOW())
                ORDER BY valid_from DESC LIMIT 1
                """,
                (city, car_type),
            )
            row = cur.fetchone()
            if row:
                return _row_to_rule(row)

            # 2) city + car_type = NULL
            cur.execute(
                """
                SELECT * FROM pricing_rules
                WHERE is_active = TRUE
                  AND city = %s AND (car_type = %s OR car_type IS NULL)
                  AND (valid_until IS NULL OR valid_until > NOW())
                ORDER BY (car_type IS NOT NULL) DESC, valid_from DESC LIMIT 1
                """,
                (city, car_type),
            )
            row = cur.fetchone()
            if row:
                return _row_to_rule(row)

        # 3) city = NULL + car_type
        cur.execute(
            """
            SELECT * FROM pricing_rules
            WHERE is_active = TRUE
              AND city IS NULL AND car_type = %s
              AND (valid_until IS NULL OR valid_until > NOW())
            ORDER BY valid_from DESC LIMIT 1
            """,
            (car_type,),
        )
        row = cur.fetchone()
        if row:
            return _row_to_rule(row)

        # 4) city = NULL + car_type = NULL (عام)
        cur.execute(
            """
            SELECT * FROM pricing_rules
            WHERE is_active = TRUE
              AND city IS NULL AND (car_type = %s OR car_type IS NULL)
              AND (valid_until IS NULL OR valid_until > NOW())
            ORDER BY (car_type IS NOT NULL) DESC, valid_from DESC LIMIT 1
            """,
            (car_type,),
        )
        row = cur.fetchone()
        if row:
            return _row_to_rule(row)

    return None


def _row_to_rule(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "city": row.get("city"),
        "car_type": row.get("car_type"),
        "base_fare": float(row["base_fare"]),
        "per_km": float(row["per_km"]),
        "per_minute": float(row["per_minute"]),
        "minimum_fare": float(row["minimum_fare"]),
        "surge_multiplier": float(row["surge_multiplier"]),
    }


# ===== Calculate price =====
def calculate_price(
    distance_meters: float,
    duration_seconds: int,
    rule: Optional[dict] = None,
    city: Optional[str] = None,
    car_type: Optional[str] = None,
) -> dict:
    """
    يحسب السعر. يرجع dict فيه:
    - base, per_km_amount, per_min_amount, subtotal, surge, price, minimum_applied
    """
    if rule is None:
        rule = get_pricing_rule(city, car_type)

    if not rule:
        # fallback: أسعار افتراضية
        logger.warning("No pricing rule found — using fallback")
        rule = {
            "base_fare": 5000.0,
            "per_km": 2000.0,
            "per_minute": 500.0,
            "minimum_fare": 8000.0,
            "surge_multiplier": 1.0,
        }

    distance_km = distance_meters / 1000.0
    duration_min = duration_seconds / 60.0

    base = rule["base_fare"]
    per_km_amount = distance_km * rule["per_km"]
    per_min_amount = duration_min * rule["per_minute"]

    subtotal = base + per_km_amount + per_min_amount

    minimum_applied = False
    if subtotal < rule["minimum_fare"]:
        subtotal = rule["minimum_fare"]
        minimum_applied = True

    surge = rule["surge_multiplier"]
    price = subtotal * surge

    return {
        "base": round(base, 2),
        "per_km_amount": round(per_km_amount, 2),
        "per_min_amount": round(per_min_amount, 2),
        "subtotal": round(subtotal, 2),
        "surge_multiplier": surge,
        "price": round(price, 2),
        "minimum_applied": minimum_applied,
        "distance_meters": round(distance_meters, 2),
        "duration_seconds": duration_seconds,
        "rule_id": rule.get("id"),
    }


# ===== Estimate (للـ endpoint /estimate) =====
def estimate_trip(
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
    city: Optional[str] = None,
    car_type: Optional[str] = None,
) -> dict:
    """تقدير كامل لرحلة (مسافة + وقت + سعر)."""
    route = driving_route(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
    if route:
        distance, duration, geometry = route
    else:
        distance = haversine_meters(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
        duration = estimate_duration_seconds(distance)
        geometry = None
    breakdown = calculate_price(distance, duration, city=city, car_type=car_type)

    return {
        "distance_meters": int(distance),
        "duration_seconds": duration,
        "price": breakdown["price"],
        "breakdown": breakdown,
        "route": geometry,
    }