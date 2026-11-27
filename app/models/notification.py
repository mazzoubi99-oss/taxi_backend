"""
Pydantic models للإشعارات
"""
from typing import Optional

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    body: str
    data: Optional[dict] = None
    sender_type: str
    is_read: bool
    created_at: str
    read_at: Optional[str] = None


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    total: int
    unread: int


class UnreadCountResponse(BaseModel):
    unread: int