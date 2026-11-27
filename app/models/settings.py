"""
Pydantic models للإعدادات
"""
from typing import Any, Optional

from pydantic import BaseModel


class SettingItem(BaseModel):
    key: str
    value: Any
    description: Optional[str] = None
    category: Optional[str] = None
    updated_at: Optional[str] = None


class SettingUpdateRequest(BaseModel):
    value: Any


class SettingsBulkUpdate(BaseModel):
    items: dict[str, Any]


class SettingsBulkResponse(BaseModel):
    updated: list[str]
    not_found: list[str]