"""
Priority service — حساب أولوية السائق للـ dispatch
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.core.database import db_cursor
from app.services import settings

logger = logging.getLogger(__name__)


# ===== Load factors =====
def get_active_factors() -> list[dict]:
    """كل عوامل الأولوية النشطة، مرتبة حسب الـ weight تنازلياً."""
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT id, code, name_ar, weight, direction, config
            FROM priority_factors
            WHERE is_active = TRUE
            ORDER BY weight DESC
            """
        )
        rows = cur.fetchall()

    return [
        {
            "id": str(r["id"]),
            "code": r["code"],
            "name_ar": r["name_ar"],
            "weight": float(r["weight"]),
            "direction": r["direction"],
            "config": r["config"] or {},
        }
        for r in rows
    ]


# ===== Individual factor calculators =====
def _distance_score(distance_meters: float, config: dict) -> float:
    max_m = config.get("max_meters", 5000)
    if max_m <= 0:
        return 1.0
    return max(0.0, 1.0 - min(distance_meters / max_m, 1.0))


def _rating_score(rating_avg: float, rating_count: int, config: dict) -> float:
    prior = config.get("bayesian_prior", 3.0)
    c = config.get("bayesian_c", 5)
    bayesian = (rating_avg * rating_count + prior * c) / (rating_count + c)
    return max(0.0, min(bayesian / 5.0, 1.0))


def _idle_time_score(last_trip_at: Optional[datetime], config: dict) -> float:
    if last_trip_at is None:
        return 1.0  # سائق جديد = أعلى أولوية خمول

    max_minutes = config.get("max_minutes", 30)
    now = datetime.now(timezone.utc)

    if last_trip_at.tzinfo is None:
        last_trip_at = last_trip_at.replace(tzinfo=timezone.utc)

    idle_minutes = (now - last_trip_at).total_seconds() / 60.0
    return max(0.0, min(idle_minutes / max_minutes, 1.0))


def _acceptance_score(accepted: int, total: int) -> float:
    if total <= 0:
        return 0.5  # محايد
    return max(0.0, min(accepted / total, 1.0))


def _rejection_score(rejected: int, total: int) -> float:
    if total <= 0:
        return 1.0  # ما في رفض = score عالي
    return max(0.0, 1.0 - min(rejected / total, 1.0))


# ===== Compute full priority =====
def compute_priority(
    driver_id: str,
    distance_meters: float,
    factors: Optional[list[dict]] = None,
) -> dict:
    """
    يحسب priority_score لسائق معين.
    يرجع dict فيه: score, breakdown
    """
    if factors is None:
        factors = get_active_factors()

    # جلب بيانات السائق
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT d.rating_avg, d.rating_count,
                   s.last_trip_completed_at, s.total_offers,
                   s.accepted_offers, s.rejected_offers
            FROM drivers d
            LEFT JOIN driver_priority_stats s ON s.driver_id = d.user_id
            WHERE d.user_id = %s
            """,
            (driver_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"score": 0.0, "breakdown": {}, "error": "driver_not_found"}

    rating_avg = float(row["rating_avg"]) if row["rating_avg"] is not None else 5.0
    rating_count = int(row["rating_count"]) if row["rating_count"] else 0
    last_trip = row["last_trip_completed_at"]
    total_offers = int(row["total_offers"]) if row["total_offers"] else 0
    accepted_offers = int(row["accepted_offers"]) if row["accepted_offers"] else 0
    rejected_offers = int(row["rejected_offers"]) if row["rejected_offers"] else 0

    breakdown = {}
    total_score = 0.0

    for f in factors:
        code = f["code"]
        weight = f["weight"]
        direction = f["direction"]
        config = f["config"]

        raw = 0.0

        if code == "distance":
            raw = _distance_score(distance_meters, config)
        elif code == "rating":
            raw = _rating_score(rating_avg, rating_count, config)
        elif code == "idle_time":
            raw = _idle_time_score(last_trip, config)
        elif code == "acceptance":
            raw = _acceptance_score(accepted_offers, total_offers)
        elif code == "rejection":
            raw = _rejection_score(rejected_offers, total_offers)
        else:
            # عامل غير معروف — نتخطاه
            logger.warning(f"Unknown priority factor: {code}")
            continue

        if direction == "negative":
            raw = 1.0 - raw

        contribution = raw * weight
        total_score += contribution

        breakdown[code] = {
            "raw": round(raw, 4),
            "weight": weight,
            "contribution": round(contribution, 4),
        }

    return {
        "score": round(total_score, 4),
        "breakdown": breakdown,
    }


# ===== Rank drivers for a trip =====
def rank_drivers_for_trip(
    pickup_lat: float,
    pickup_lng: float,
    candidates: list[dict],
    factors: Optional[list[dict]] = None,
) -> list[dict]:
    """
    candidates: list of dicts من find_nearby_drivers (فيها driver_id, distance_meters, ...)
    يرجع نفس القائمة + priority_score + breakdown، مرتبة تنازلياً.
    """
    if factors is None:
        factors = get_active_factors()

    ranked = []
    for c in candidates:
        p = compute_priority(c["driver_id"], c["distance_meters"], factors)
        ranked.append({
            **c,
            "priority_score": p["score"],
            "priority_breakdown": p.get("breakdown", {}),
        })

    ranked.sort(key=lambda x: x["priority_score"], reverse=True)
    return ranked