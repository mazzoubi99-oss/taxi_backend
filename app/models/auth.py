"""
Pydantic models للـ Auth
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ===== Register =====
class RegisterRequest(BaseModel):
    phone: str = Field(..., min_length=8, max_length=20)
    full_name: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=6, max_length=100)
    role: Literal["rider", "driver"] = "rider"
    email: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        v = v.strip().replace(" ", "").replace("-", "")
        if not v.isdigit() and not (v.startswith("+") and v[1:].isdigit()):
            raise ValueError("رقم الهاتف يجب أن يحتوي أرقام فقط")
        return v


# ===== Login =====
class LoginRequest(BaseModel):
    phone: str
    password: str


# ===== Refresh =====
class RefreshRequest(BaseModel):
    refresh_token: str


# ===== Responses =====
class UserResponse(BaseModel):
    id: str
    phone: str
    full_name: str
    email: Optional[str] = None
    role: str
    is_active: bool
    is_verified: bool
    avatar_url: Optional[str] = None
    language: str = "ar"


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class ProfileUpdateRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)

    @field_validator("full_name", mode="before")
    @classmethod
    def trim_full_name(cls, value):
        return value.strip() if isinstance(value, str) else value
