"""
Admin Wallet Router
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import db_cursor
from app.core.deps import require_role
from app.models.wallet import (
    AdminAdjustRequest,
    AdminDepositRequest,
    AdminLockRequest,
    AdminReviewRequest,
    AdminWithdrawRequest,
    RequestResponse,
    TransactionListResponse,
    TransactionResponse,
    WalletResponse,
)
from app.services import wallet as wallet_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== GET /{user_id} =====
@router.get("/{user_id}", response_model=WalletResponse, summary="محفظة مستخدم")
async def get_user_wallet(user_id: str, _admin: dict = Depends(require_role("admin"))):
    w = wallet_service.get_wallet(user_id)
    if not w:
        raise HTTPException(status_code=404, detail="المحفظة غير موجودة")
    return WalletResponse(**w)


# ===== GET /{user_id}/transactions =====
@router.get(
    "/{user_id}/transactions",
    response_model=TransactionListResponse,
    summary="حركات محفظة مستخدم",
)
async def get_user_transactions(
    user_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    txs = wallet_service.get_transactions(user_id, limit, offset)
    total = wallet_service.get_transactions_count(user_id)
    return TransactionListResponse(
        transactions=[TransactionResponse(**t) for t in txs],
        total=total,
    )


# ===== POST /{user_id}/deposit =====
@router.post("/{user_id}/deposit", summary="إيداع في محفظة")
async def admin_deposit(
    user_id: str,
    data: AdminDepositRequest,
    admin: dict = Depends(require_role("admin")),
):
    result = wallet_service.deposit(
        user_id, data.amount, admin_id=admin["sub"],
        description=data.description,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error_message"))
    return result


# ===== POST /{user_id}/withdraw =====
@router.post("/{user_id}/withdraw", summary="سحب من محفظة")
async def admin_withdraw(
    user_id: str,
    data: AdminWithdrawRequest,
    admin: dict = Depends(require_role("admin")),
):
    result = wallet_service.withdraw(
        user_id, data.amount, admin_id=admin["sub"],
        description=data.description,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error_message"))
    return result


# ===== POST /{user_id}/adjust =====
@router.post("/{user_id}/adjust", summary="تعديل رصيد إداري")
async def admin_adjust(
    user_id: str,
    data: AdminAdjustRequest,
    admin: dict = Depends(require_role("admin")),
):
    result = wallet_service.adjust(
        user_id, data.amount, admin_id=admin["sub"],
        description=data.description,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error_message"))
    return result


# ===== POST /{user_id}/lock =====
@router.post("/{user_id}/lock", summary="قفل محفظة")
async def admin_lock(
    user_id: str,
    data: AdminLockRequest,
    admin: dict = Depends(require_role("admin")),
):
    if not wallet_service.lock_wallet(user_id, data.reason, admin["sub"]):
        raise HTTPException(status_code=400, detail="فشل القفل")
    return {"status": "success", "locked": True}


# ===== POST /{user_id}/unlock =====
@router.post("/{user_id}/unlock", summary="فتح محفظة")
async def admin_unlock(user_id: str, _admin: dict = Depends(require_role("admin"))):
    if not wallet_service.unlock_wallet(user_id):
        raise HTTPException(status_code=400, detail="فشل الفتح")
    return {"status": "success", "locked": False}


# ===== Deposit requests =====
@router.get("/deposit-requests/list", response_model=list[RequestResponse], summary="كل طلبات الشحن")
async def list_deposit_requests(
    status_filter: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    where = "1=1"
    params: list = []
    if status_filter:
        where = "status = %s"
        params.append(status_filter)

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"""
            SELECT id, user_id, amount, status, method, note,
                   admin_note, requested_at, reviewed_at
            FROM deposit_requests WHERE {where}
            ORDER BY requested_at DESC LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()
    return [_row_to_request(r) for r in rows]


@router.post("/deposit-requests/{request_id}/approve", summary="موافقة على طلب شحن")
async def approve_deposit_request(
    request_id: str,
    data: AdminReviewRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT user_id, amount, status FROM deposit_requests WHERE id = %s",
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="الطلب غير موجود")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="الطلب ليس قيد الانتظار")

        # إيداع
        result = wallet_service.deposit(
            str(row["user_id"]), float(row["amount"]),
            admin_id=admin["sub"],
            description=f"شحن محفظة - طلب {request_id}",
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error_message"))

        cur.execute(
            """
            UPDATE deposit_requests
            SET status = 'approved', admin_note = %s,
                reviewed_at = NOW(), reviewed_by = %s
            WHERE id = %s
            """,
            (data.admin_note, admin["sub"], request_id),
        )

    return {"status": "success", "new_balance": result["new_balance"]}


@router.post("/deposit-requests/{request_id}/reject", summary="رفض طلب شحن")
async def reject_deposit_request(
    request_id: str,
    data: AdminReviewRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE deposit_requests
            SET status = 'rejected', admin_note = %s,
                reviewed_at = NOW(), reviewed_by = %s
            WHERE id = %s AND status = 'pending'
            """,
            (data.admin_note, admin["sub"], request_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=400, detail="الطلب غير موجود أو تم معالجته")
    return {"status": "success"}


# ===== Withdrawal requests =====
@router.get("/withdrawals/list", response_model=list[RequestResponse], summary="كل طلبات السحب")
async def list_withdrawal_requests(
    status_filter: str | None = Query(None, pattern="^(pending|approved|rejected|paid)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_role("admin")),
):
    where = "1=1"
    params: list = []
    if status_filter:
        where = "status = %s"
        params.append(status_filter)

    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            f"""
            SELECT id, user_id, amount, status, method, note,
                   admin_note, requested_at, reviewed_at            FROM withdrawal_requests WHERE {where}
            ORDER BY requested_at DESC LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()
    return [_row_to_request(r) for r in rows]


@router.post("/withdrawals/{request_id}/approve", summary="موافقة على سحب")
async def approve_withdrawal(
    request_id: str,
    data: AdminReviewRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT user_id, amount, status FROM withdrawal_requests WHERE id = %s",
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="الطلب غير موجود")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="الطلب ليس قيد الانتظار")

        # خصم
        result = wallet_service.withdraw(
            str(row["user_id"]), float(row["amount"]),
            admin_id=admin["sub"],
            description=f"سحب - طلب {request_id}",
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error_message"))

        cur.execute(
            """
            UPDATE withdrawal_requests
            SET status = 'approved', admin_note = %s,
                reviewed_at = NOW(), reviewed_by = %s
            WHERE id = %s
            """,
            (data.admin_note, admin["sub"], request_id),
        )

    return {"status": "success", "new_balance": result["new_balance"]}


@router.post("/withdrawals/{request_id}/reject", summary="رفض سحب")
async def reject_withdrawal(
    request_id: str,
    data: AdminReviewRequest,
    admin: dict = Depends(require_role("admin")),
):
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE withdrawal_requests
            SET status = 'rejected', admin_note = %s,
                reviewed_at = NOW(), reviewed_by = %s
            WHERE id = %s AND status = 'pending'
            """,
            (data.admin_note, admin["sub"], request_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=400, detail="الطلب غير موجود أو تم معالجته")
    return {"status": "success"}


@router.post("/withdrawals/{request_id}/mark-paid", summary="تم الدفع")
async def mark_paid(request_id: str, _admin: dict = Depends(require_role("admin"))):
    with db_cursor() as cur:
        cur.execute(
            "UPDATE withdrawal_requests SET status = 'paid', paid_at = NOW() "
            "WHERE id = %s AND status = 'approved'",
            (request_id,),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=400, detail="الطلب لازم يكون approved أولاً")
    return {"status": "success"}


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