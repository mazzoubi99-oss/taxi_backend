"""
Pydantic models للأدمن
"""
from typing import Optional

from pydantic import BaseModel, Field


class DriverActionRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


class DriverRejectRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class DriverBanRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class AdminDriverListItem(BaseModel):
    user_id: str
    phone: str
    full_name: str
    car_model: str
    car_plate: str
    car_type: str
    account_status: str
    availability_status: str
    rating_avg: float
    total_trips: int
    created_at: str


class AdminDocumentResponse(BaseModel):
    doc_type: str
    mime_type: str
    uploaded_at: str
    image_base64: Optional[str] = None


class AdminDriverDetailResponse(AdminDriverListItem):
    email: Optional[str] = None
    car_color: Optional[str] = None
    car_year: Optional[int] = None
    account_status_note: Optional[str] = None
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    wallet_balance: float
    rating_count: int
    documents: list[AdminDocumentResponse] = []


class AdminDriverListResponse(BaseModel):
    drivers: list[AdminDriverListItem]
    total: int