"""
Pydantic models للـ Promo + Zones + Discounts
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ===== Validate =====
class PromoValidateRequest(BaseModel):
    code: str = Field(..., min_length=3, max_length=30)
    pickup_lat: float = Field(..., ge=-90, le=90)
    pickup_lng: float = Field(..., ge=-180, le=180)
    trip_price: float = Field(..., gt=0)
    car_type: Optional[str] = None


class PromoValidateResponse(BaseModel):
    is_valid: bool
    error_message: Optional[str] = None
    promo_id: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    discount_amount: float = 0
    final_price: float


# ===== Admin Create/Update =====
class PromoCreateRequest(BaseModel):
    code: str = Field(..., min_length=3, max_length=30)
    description: Optional[str] = None

    discount_type: Literal["percentage", "fixed"]
    discount_value: float = Field(..., gt=0)
    max_discount_amount: Optional[float] = None

    min_trip_amount: float = 0
    max_uses: Optional[int] = Field(None, ge=1)
    max_uses_per_user: Optional[int] = Field(None, ge=1)

    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    is_active: bool = True

    target_user_id: Optional[str] = None
    target_zone_id: Optional[str] = None
    applicable_car_types: Optional[list[str]] = None
    first_trip_only: bool = False


class PromoUpdateRequest(BaseModel):
    description: Optional[str] = None
    discount_type: Optional[Literal["percentage", "fixed"]] = None
    discount_value: Optional[float] = Field(None, gt=0)
    max_discount_amount: Optional[float] = None
    min_trip_amount: Optional[float] = None
    max_uses: Optional[int] = None
    max_uses_per_user: Optional[int] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    is_active: Optional[bool] = None
    target_user_id: Optional[str] = None
    target_zone_id: Optional[str] = None
    applicable_car_types: Optional[list[str]] = None
    first_trip_only: Optional[bool] = None


class PromoResponse(BaseModel):
    id: str
    code: str
    description: Optional[str] = None
    discount_type: str
    discount_value: float
    max_discount_amount: Optional[float] = None
    min_trip_amount: float
    max_uses: Optional[int] = None
    max_uses_per_user: Optional[int] = None
    used_count: int
    valid_from: str
    valid_until: Optional[str] = None
    is_active: bool
    target_user_id: Optional[str] = None
    target_zone_id: Optional[str] = None
    applicable_car_types: Optional[list[str]] = None
    first_trip_only: bool
    created_at: str


class PromoListResponse(BaseModel):
    promos: list[PromoResponse]
    total: int


class PromoUseResponse(BaseModel):
    id: str
    promo_code_id: str
    user_id: str
    trip_id: Optional[str] = None
    discount_amount: float
    used_at: str


# ===== Zones =====
class ZoneCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    city: Optional[str] = None
    boundary_geojson: dict


class ZoneResponse(BaseModel):
    id: str
    name: str
    city: Optional[str] = None
    is_active: bool
    created_at: str