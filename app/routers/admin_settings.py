"""
Admin Settings Router
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import require_role
from app.models.settings import (
    SettingItem,
    SettingsBulkResponse,
    SettingsBulkUpdate,
    SettingUpdateRequest,
)
from app.services import settings as settings_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== GET / =====
@router.get("", response_model=list[SettingItem], summary="كل الإعدادات")
async def list_settings(_admin: dict = Depends(require_role("admin"))):
    rows = settings_service.get_all()
    return [SettingItem(**r) for r in rows]


# ===== PUT /bulk =====
@router.put("/bulk", response_model=SettingsBulkResponse, summary="تعديل عدة إعدادات")
async def bulk_update(
    data: SettingsBulkUpdate,
    admin: dict = Depends(require_role("admin")),
):
    result = settings_service.set_settings_bulk(data.items, admin["sub"])
    return SettingsBulkResponse(**result)


# ===== GET /{key} =====
@router.get("/{key}", response_model=SettingItem, summary="إعداد واحد")
async def get_setting(key: str, _admin: dict = Depends(require_role("admin"))):
    rows = settings_service.get_all()
    for r in rows:
        if r["key"] == key:
            return SettingItem(**r)
    raise HTTPException(status_code=404, detail="الإعداد غير موجود")


# ===== PUT /{key} =====
@router.put("/{key}", summary="تعديل إعداد")
async def update_setting(
    key: str,
    data: SettingUpdateRequest,
    admin: dict = Depends(require_role("admin")),
):
    if not settings_service.set_setting(key, data.value, admin["sub"]):
        raise HTTPException(status_code=404, detail="الإعداد غير موجود")
    return {"status": "success", "key": key, "value": data.value}