"""
Pydantic models للـ Drivers
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ===== Enums =====
AccountStatus = Literal["pending", "approved", "rejected", "banned"]
AvailabilityStatus = Literal["offline", "online", "on_trip"]
CarType = Literal["sedan", "suv", "van", "motorcycle", "truck"]
DocType = Literal[
    "car_front", "car_back",
    "license", "vehicle_registration",
    "extra_1", "extra_2",
]


# ===== Vehicle Update =====
class VehicleUpdateRequest(BaseModel):
    car_model: Optional[str] = Field(None, max_length=80)
    car_plate: Optional[str] = Field(None, max_length=20)
    car_color: Optional[str] = Field(None, max_length=30)
    car_year: Optional[int] = Field(None, ge=1980, le=2100)
    car_type: Optional[CarType] = None

    @field_validator("car_plate")
    @classmethod
    def clean_plate(cls, v):
        if v is None:
            return v
        return v.strip().upper()


# ===== Documents =====
class DocumentUploadRequest(BaseModel):
    doc_type: DocType
    image_base64: str = Field(..., min_length=100)
    mime_type: str = Field("image/jpeg", max_length=30)

    @field_validator("image_base64")
    @classmethod
    def validate_size(cls, v):
        # تقدير الحجم: base64 ~ 4/3 من الحجم الأصلي
        # 2MB → ~2.8M حرف base64
        max_b64_len = 3 * 1024 * 1024  # ~3M حرف
        if len(v) > max_b64_len:
            raise ValueError("حجم الصورة أكبر من 2MB")
        return v


class DocumentResponse(BaseModel):
    doc_type: str
    mime_type: str
    uploaded_at: str
    updated_at: str


class DocumentWithImageResponse(DocumentResponse):
    image_base64: str


# ===== Location =====
class LocationUpdateRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


# ===== Driver Info =====
class DriverMeResponse(BaseModel):
    user_id: str
    phone: str
    full_name: str
    email: Optional[str] = None

    car_model: str
    car_plate: str
    car_color: Optional[str] = None
    car_year: Optional[int] = None
    car_type: str

    account_status: str
    account_status_note: Optional[str] = None
    availability_status: str

    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    last_location_at: Optional[str] = None

    rating_avg: float
    rating_count: int
    total_trips: int
    wallet_balance: float

    documents: list[DocumentResponse] = []


# ===== Nearby Drivers =====
class NearbyDriver(BaseModel):
    driver_id: str
    full_name: str
    car_model: str
    car_plate: str
    car_color: Optional[str] = None
    car_type: str
    rating_avg: float
    distance_meters: float
    lat: float
    lng: float