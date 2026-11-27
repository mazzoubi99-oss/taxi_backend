"""
Wallet Router — للمستخدم
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2 import errors

from app.core.database import db_cursor
from app.core.deps import get_current_user
from app.models.wallet import (
    DepositRequestCreate,
    RequestResponse,
    TransactionListResponse,
    TransactionResponse,
    WalletResponse,
    WithdrawalRequestCreate,
)
from app.services import wallet as wallet_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== GET /me =====
@router.get("/me", response_model=WalletResponse, summary="محفظتي")
async def my_wallet(user: dict = Depends(get_current_user)):
    w = wallet_service.get_wallet(user["sub"])
    if not w:
        raise HTTPException(status_code=404, detail="المحفظة غير موجودة")
    return WalletResponse(**w)


# ===== GET /transactions =====
@router.get(
    "/transactions",
    response_model=TransactionListResponse,
    summary="حركات محفظتي",
)
async def my_transactions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    type_filter: str | None = Query(None),
    user: dict = Depends(get_current_user),
):
    txs = wallet_service.get_transactions(user["sub"], limit, offset, type_filter)
    total = wallet_service.get_transactions_count(user["sub"], type_filter)
    return TransactionListResponse(
        transactions=[TransactionResponse(**t) for t in txs],
        total=total,
    )


# ===== POST /deposit-requests =====
@router.post(
    "/deposit-requests",
    response_model=RequestResponse,
    status_code=201,
    summary="طلب شحن محفظة",
)
async def create_deposit_request(
    data: DepositRequestCreate,
    user: dict = Depends(get_current_user),
):
    import json
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            INSERT INTO deposit_requests
                (user_id, amount, method, reference_info, note)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            RETURNING id, user_id, amount, status, method, note,
                      admin_note, requested_at, reviewed_at
            """,
            (
                user["sub"], data.amount, data.method,
                json.dumps(data.reference_info) if data.reference_info else None,
                data.note,
            ),
        )
        row = cur.fetchone()

    return _row_to_request(row)


# ===== GET /deposit-requests =====
@router.get(
    "/deposit-requests",
    response_model=list[RequestResponse],
    summary="طلبات الشحن الخاصة بي",
)
async def my_deposit_requests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT id, user_id, amount, status, method, note,
                   admin_note, requested_at, reviewed_at
            FROM deposit_requests WHERE user_id = %s
            ORDER BY requested_at DESC LIMIT %s OFFSET %s
            """,
            (user["sub"], limit, offset),
        )
        rows = cur.fetchall()
    return [_row_to_request(r) for r in rows]


# ===== POST /withdrawals =====
@router.post(
    "/withdrawals",
    response_model=RequestResponse,
    status_code=201,
    summary="طلب سحب",
)
async def create_withdrawal(
    data: WithdrawalRequestCreate,
    user: dict = Depends(get_current_user),
):
    import json
    from app.services import settings

    # تحقق من الرصيد
    w = wallet_service.get_wallet(user["sub"])
    if not w:
        raise HTTPException(status_code=404, detail="المحفظة غير موجودة")
    if w["is_locked"]:
        raise HTTPException(status_code=403, detail="المحفظة مقفلة")
    if w["balance"] < data.amount:
        raise HTTPException(status_code=400, detail="الرصيد غير كافٍ")

    # تحقق من الحد الأدنى
    min_amount = settings.get_float("wallet.min_withdrawal_amount", 0)
    if data.amount < min_amount:
        raise HTTPException(
            status_code=400,
            detail=f"الحد الأدنى للسحب {min_amount}",
        )

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            INSERT INTO withdrawal_requests
                (user_id, amount, method, account_info, note)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            RETURNING id, user_id, amount, status, method, note,
                      admin_note, requested_at, reviewed_at
            """,
            (
                user["sub"], data.amount, data.method,
                json.dumps(data.account_info) if data.account_info else None,
                data.note,
            ),
        )
        row = cur.fetchone()

    return _row_to_request(row)


# ===== GET /withdrawals =====
@router.get(
    "/withdrawals",
    response_model=list[RequestResponse],
    summary="طلبات السحب الخاصة بي",
)
async def my_withdrawals(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT id, user_id, amount, status, method, note,
                   admin_note, requested_at, reviewed_at
            FROM withdrawal_requests WHERE user_id = %s
            ORDER BY requested_at DESC LIMIT %s OFFSET %s
            """,
            (user["sub"], limit, offset),
        )
        rows = cur.fetchall()
    return [_row_to_request(r) for r in rows]


def _row_to_request(row: dict) -> RequestResponse:
    return RequestResponse(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        amount=float(row["amount"]),
        status=row["status"],
        method=row["method"],
        note=row.get("note"),
        admin_note=row.get("admin_note"),
        requested_at=row["requested_at"].isoformat(),
        reviewed_at=row["reviewed_at"].isoformat() if row.get("reviewed_at") else None,
    )