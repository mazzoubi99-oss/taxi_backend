"""
Pydantic models للرحلات
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ===== Estimate =====
class TripEstimateRequest(BaseModel):
    pickup_lat: float = Field(..., ge=-90, le=90)
    pickup_lng: float = Field(..., ge=-180, le=180)
    dropoff_lat: float = Field(..., ge=-90, le=90)
    dropoff_lng: float = Field(..., ge=-180, le=180)
    car_type: Optional[str] = None
    city: Optional[str] = None


class TripEstimateResponse(BaseModel):
    distance_meters: int
    duration_seconds: int
    price: float
    breakdown: dict


# ===== Request =====
class TripRequestCreate(BaseModel):
    pickup_lat: float = Field(..., ge=-90, le=90)
    pickup_lng: float = Field(..., ge=-180, le=180)
    pickup_address: Optional[str] = None
    dropoff_lat: float = Field(..., ge=-90, le=90)
    dropoff_lng: float = Field(..., ge=-180, le=180)
    dropoff_address: Optional[str] = None
    car_type: Optional[str] = None
    city: Optional[str] = None
    payment_method: Literal["cash", "wallet", "card"] = "cash"
    promo_code: Optional[str] = None
    rider_note: Optional[str] = None


class TripRequestResponse(BaseModel):
    success: bool
    trip_id: Optional[str] = None
    price_estimate: Optional[float] = None
    final_price: Optional[float] = None
    discount_amount: Optional[float] = None
    distance_meters: Optional[int] = None
    duration_seconds: Optional[int] = None
    offers_count: Optional[int] = None
    start_code: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


# ===== Trip details =====
class TripDetail(BaseModel):
    id: str
    status: str
    rider_id: str
    driver_id: Optional[str] = None

    pickup_lat: float
    pickup_lng: float
    pickup_address: Optional[str] = None
    dropoff_lat: float
    dropoff_lng: float
    dropoff_address: Optional[str] = None

    distance_meters: Optional[int] = None
    duration_seconds: Optional[int] = None

    price_estimate: Optional[float] = None
    price_final: Optional[float] = None
    discount_amount: float = 0
    payment_method: str
    currency: str = "SYP"

    start_code: Optional[str] = None  # يظهر للراكب فقط

    requested_at: str
    accepted_at: Optional[str] = None
    arrived_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancelled_at: Optional[str] = None

    cancellation_reason_id: Optional[str] = None
    cancellation_reason_text: Optional[str] = None

    rider_rating: Optional[int] = None
    driver_rating: Optional[int] = None

    # معلومات السائق (لو مقبول)
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    car_model: Optional[str] = None
    car_plate: Optional[str] = None
    car_color: Optional[str] = None

    # معلومات الراكب (للسائق)
    rider_name: Optional[str] = None
    rider_phone: Optional[str] = None


# ===== Driver actions =====
class TripAcceptResponse(BaseModel):
    success: bool
    trip_id: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


class TripRejectRequest(BaseModel):
    reason_id: Optional[str] = None
    reason_text: Optional[str] = None


class TripStartRequest(BaseModel):
    code: Optional[str] = None


# ===== Cancel =====
class TripCancelRequest(BaseModel):
    reason_id: Optional[str] = None
    reason_text: Optional[str] = None


# ===== Available (driver) =====
class AvailableTrip(BaseModel):
    trip_id: str
    pickup_lat: float
    pickup_lng: float
    pickup_address: Optional[str] = None
    dropoff_lat: float
    dropoff_lng: float
    dropoff_address: Optional[str] = None
    distance_meters: Optional[int] = None
    duration_seconds: Optional[int] = None
    price_estimate: Optional[float] = None
    pickup_distance_meters: Optional[int] = None  # المسافة من السائق
    priority_score: Optional[float] = None
    expires_at: Optional[str] = None
    requested_at: str


# ===== List =====
class TripListItem(BaseModel):
    id: str
    status: str
    rider_id: str
    driver_id: Optional[str] = None
    pickup_address: Optional[str] = None
    dropoff_address: Optional[str] = None
    price_estimate: Optional[float] = None
    price_final: Optional[float] = None
    requested_at: str
    completed_at: Optional[str] = None


class TripListResponse(BaseModel):
    trips: list[TripListItem]
    total: int


# ===== Admin =====
class AdminReassignRequest(BaseModel):
    new_driver_id: str
    reason: Optional[str] = None


class AdminForceCancelRequest(BaseModel):
    reason: str = Field(..., min_length=3)