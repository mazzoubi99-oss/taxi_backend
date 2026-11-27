"""
Admin Priority Factors Router — CRUD
"""
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from psycopg2 import errors

from app.core.database import db_cursor
from app.core.deps import require_role

logger = logging.getLogger(__name__)
router = APIRouter()


class PriorityFactorCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name_ar: str = Field(..., min_length=2, max_length=100)
    name_en: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    weight: float = Field(..., ge=0, le=1)
    direction: Literal["positive", "negative"] = "positive"
    config: dict = {}
    is_active: bool = True


class PriorityFactorUpdate(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    weight: Optional[float] = None
    direction: Optional[Literal["positive", "negative"]] = None
    config: Optional[dict] = None
    is_active: Optional[bool] = None


def _row(r):
    return {
        "id": str(r["id"]),
        "code": r["code"],
        "name_ar": r["name_ar"],
        "name_en": r["name_en"],
        "description": r["description"],
        "weight": float(r["weight"]),
        "direction": r["direction"],
        "config": r["config"] or {},
        "is_active": r["is_active"],
        "created_at": r["created_at"].isoformat(),
        "updated_at": r["updated_at"].isoformat(),
    }


@router.get("", summary="كل عوامل الأولوية")
async def list_factors(_admin: dict = Depends(require_role("admin"))):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT * FROM priority_factors ORDER BY weight DESC, code ASC"
        )
        rows = cur.fetchall()

        cur.execute(
            "SELECT COALESCE(SUM(weight), 0) AS total FROM priority_factors WHERE is_active = TRUE"
        )
        total_weight = float(cur.fetchone()["total"])

    return {
        "factors": [_row(r) for r in rows],
        "total_weight": total_weight,
        "is_valid": abs(total_weight - 1.0) < 0.001,
    }


@router.post("", status_code=201, summary="إنشاء عامل")
async def create_factor(data: PriorityFactorCreate, _admin: dict = Depends(require_role("admin"))):
    try:
        with db_cursor(dict_cursor=True) as cur:
            import json
            cur.execute(
                """
                INSERT INTO priority_factors
                    (code, name_ar, name_en, description, weight, direction, config, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                RETURNING *
                """,
                (
                    data.code, data.name_ar, data.name_en, data.description,
                    data.weight, data.direction, json.dumps(data.config), data.is_active,
                ),
            )
            row = cur.fetchone()
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="الكود موجود بالفعل")

    return _row(row)


@router.put("/{factor_id}", summary="تعديل عامل")
async def update_factor(
    factor_id: str,
    data: PriorityFactorUpdate,
    _admin: dict = Depends(require_role("admin")),
):
    import json
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="لا يوجد بيانات للتحديث")

    if "config" in updates:
        updates["config"] = json.dumps(updates["config"])

    set_clause = []
    values = []
    for k, v in updates.items():
        if k == "config":
            set_clause.append(f"{k} = %s::jsonb")
        else:
            set_clause.append(f"{k} = %s")
        values.append(v)

    values.append(factor_id)

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"UPDATE priority_factors SET {', '.join(set_clause)} WHERE id = %s RETURNING *",
            values,
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="العامل غير موجود")

    return _row(row)


@router.delete("/{factor_id}", summary="حذف عامل")
async def delete_factor(factor_id: str, _admin: dict = Depends(require_role("admin"))):
    with db_cursor() as cur:
        cur.execute("DELETE FROM priority_factors WHERE id = %s", (factor_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="العامل غير موجود")
    return {"status": "success"}