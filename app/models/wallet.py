"""
Pydantic models للمحفظة
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class WalletResponse(BaseModel):
    user_id: str
    balance: float
    currency: str
    is_locked: bool
    lock_reason: Optional[str] = None
    total_credited: float
    total_debited: float
    created_at: str
    updated_at: str


class TransactionResponse(BaseModel):
    id: str
    type: str
    amount: float
    balance_before: float
    balance_after: float
    currency: str
    affects_balance: bool
    trip_id: Optional[str] = None
    description: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    created_at: str


class TransactionListResponse(BaseModel):
    transactions: list[TransactionResponse]
    total: int


class DepositRequestCreate(BaseModel):
    amount: float = Field(..., gt=0)
    method: Literal["cash", "bank", "mobile_wallet"]
    reference_info: Optional[dict] = None
    note: Optional[str] = None


class WithdrawalRequestCreate(BaseModel):
    amount: float = Field(..., gt=0)
    method: Literal["cash", "bank", "mobile_wallet"]
    account_info: Optional[dict] = None
    note: Optional[str] = None


class RequestResponse(BaseModel):
    id: str
    user_id: str
    amount: float
    status: str
    method: str
    note: Optional[str] = None
    admin_note: Optional[str] = None
    requested_at: str
    reviewed_at: Optional[str] = None


# ===== Admin =====
class AdminDepositRequest(BaseModel):
    amount: float = Field(..., gt=0)
    description: Optional[str] = None


class AdminWithdrawRequest(BaseModel):
    amount: float = Field(..., gt=0)
    description: Optional[str] = None


class AdminAdjustRequest(BaseModel):
    amount: float = Field(..., description="موجب للإضافة، سالب للخصم")
    description: str = Field(..., min_length=3)


class AdminLockRequest(BaseModel):
    reason: str = Field(..., min_length=3)


class AdminReviewRequest(BaseModel):
    admin_note: Optional[str] = None