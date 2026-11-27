"""
WebSocket message protocol — Pydantic models
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ============================================================
# Client → Server
# ============================================================
class WSLocationUpdate(BaseModel):
    type: Literal["location_update"] = "location_update"
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    heading: Optional[float] = None
    speed: Optional[float] = None


class WSPing(BaseModel):
    type: Literal["ping"] = "ping"


# ============================================================
# Server → Client (للتوصيف فقط — نرسل dicts)
# ============================================================
class WSMessage(BaseModel):
    """رسالة عامة."""
    type: str
    data: Optional[dict] = None


class WSTripOffer(BaseModel):
    type: Literal["trip_offer"] = "trip_offer"
    trip_id: str
    pickup: dict
    dropoff: dict
    price_estimate: Optional[float] = None
    distance_to_pickup_meters: Optional[float] = None
    priority_score: Optional[float] = None
    expires_at: Optional[str] = None
    requested_at: str


class WSTripAccepted(BaseModel):
    type: Literal["trip_accepted"] = "trip_accepted"
    trip_id: str
    driver: dict


class WSDriverLocation(BaseModel):
    type: Literal["driver_location"] = "driver_location"
    trip_id: str
    lat: float
    lng: float
    heading: Optional[float] = None
    speed: Optional[float] = None
    at: str


class WSTripStatus(BaseModel):
    type: Literal["trip_status"] = "trip_status"
    trip_id: str
    status: str
    at: str
    extra: Optional[dict] = None


class WSTripOfferExpired(BaseModel):
    type: Literal["trip_offer_expired"] = "trip_offer_expired"
    trip_id: str


class WSTripTaken(BaseModel):
    type: Literal["trip_taken"] = "trip_taken"
    trip_id: str


class WSTripCancelled(BaseModel):
    type: Literal["trip_cancelled"] = "trip_cancelled"
    trip_id: str
    reason: Optional[str] = None
    by: Optional[str] = None


class WSNotification(BaseModel):
    type: Literal["notification"] = "notification"
    notification: dict


# ============================================================
# Helper: تحويل Pydantic → dict مع type
# ============================================================
def to_message(model: BaseModel) -> dict:
    return model.model_dump(exclude_none=True)