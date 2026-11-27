"""
Admin Cancellation Reasons Router — CRUD
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


class ReasonCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name_ar: str = Field(..., min_length=2, max_length=150)
    applies_to: Literal["rider", "driver", "both"] = "both"
    requires_note: bool = False
    counts_as_rejection: bool = True
    is_active: bool = True
    sort_order: int = 0


class ReasonUpdate(BaseModel):
    name_ar: Optional[str] = None
    applies_to: Optional[Literal["rider", "driver", "both"]] = None
    requires_note: Optional[bool] = None
    counts_as_rejection: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


def _row(r):
    return {
        "id": str(r["id"]),
        "code": r["code"],
        "name_ar": r["name_ar"],
        "applies_to": r["applies_to"],
        "requires_note": r["requires_note"],
        "counts_as_rejection": r["counts_as_rejection"],
        "is_active": r["is_active"],
        "sort_order": r["sort_order"],
        "created_at": r["created_at"].isoformat(),
        "updated_at": r["updated_at"].isoformat(),
    }


@router.get("", summary="كل أسباب الإلغاء")
async def list_reasons(_admin: dict = Depends(require_role("admin"))):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT * FROM cancellation_reasons ORDER BY applies_to, sort_order, code"
        )
        rows = cur.fetchall()
    return {"reasons": [_row(r) for r in rows]}


@router.post("", status_code=201, summary="إنشاء سبب")
async def create_reason(data: ReasonCreate, _admin: dict = Depends(require_role("admin"))):
    try:
        with db_cursor(dict_cursor=True) as cur:
            cur.execute(
                """
                INSERT INTO cancellation_reasons
                    (code, name_ar, applies_to, requires_note, counts_as_rejection, is_active, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    data.code, data.name_ar, data.applies_to,
                    data.requires_note, data.counts_as_rejection,
                    data.is_active, data.sort_order,
                ),
            )
            row = cur.fetchone()
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="الكود موجود بالفعل")

    return _row(row)


@router.put("/{reason_id}", summary="تعديل سبب")
async def update_reason(
    reason_id: str,
    data: ReasonUpdate,
    _admin: dict = Depends(require_role("admin")),
):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="لا يوجد بيانات للتحديث")

    set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
    values = list(updates.values()) + [reason_id]

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"UPDATE cancellation_reasons SET {set_clause} WHERE id = %s RETURNING *",
            values,
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="السبب غير موجود")

    return _row(row)


@router.delete("/{reason_id}", summary="حذف سبب")
async def delete_reason(reason_id: str, _admin: dict = Depends(require_role("admin"))):
    with db_cursor() as cur:
        cur.execute("DELETE FROM cancellation_reasons WHERE id = %s", (reason_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="السبب غير موجود")
    return {"status": "success"}