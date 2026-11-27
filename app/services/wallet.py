"""
Wallet service — منطق المحفظة
"""
import logging
from typing import Optional

from app.core.database import db_cursor
from app.services import settings

logger = logging.getLogger(__name__)


# ===== Read =====
def get_wallet(user_id: str) -> Optional[dict]:
    """يرجع رصيد المحفظة أو None لو ما موجودة."""
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT user_id, balance, currency, is_locked, lock_reason,
                   total_credited, total_debited, created_at, updated_at
            FROM wallets WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "user_id": str(row["user_id"]),
        "balance": float(row["balance"]),
        "currency": row["currency"],
        "is_locked": row["is_locked"],
        "lock_reason": row.get("lock_reason"),
        "total_credited": float(row["total_credited"]),
        "total_debited": float(row["total_debited"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def get_transactions(user_id: str, limit: int = 20, offset: int = 0,
                     type_filter: Optional[str] = None) -> list[dict]:
    with db_cursor(dict_cursor=True) as cur:
        where = "user_id = %s"
        params: list = [user_id]
        if type_filter:
            where += " AND type = %s"
            params.append(type_filter)

        cur.execute(
            f"""
            SELECT id, type, amount, balance_before, balance_after,
                   currency, affects_balance, trip_id, description,
                   reference_type, reference_id, created_at
            FROM wallet_transactions
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    return [
        {
            "id": str(r["id"]),
            "type": r["type"],
            "amount": float(r["amount"]),
            "balance_before": float(r["balance_before"]),
            "balance_after": float(r["balance_after"]),
            "currency": r["currency"],
            "affects_balance": r["affects_balance"],
            "trip_id": str(r["trip_id"]) if r["trip_id"] else None,
            "description": r.get("description"),
            "reference_type": r.get("reference_type"),
            "reference_id": str(r["reference_id"]) if r.get("reference_id") else None,
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


def get_transactions_count(user_id: str, type_filter: Optional[str] = None) -> int:
    with db_cursor(dict_cursor=True) as cur:
        where = "user_id = %s"
        params: list = [user_id]
        if type_filter:
            where += " AND type = %s"
            params.append(type_filter)

        cur.execute(f"SELECT COUNT(*) AS c FROM wallet_transactions WHERE {where}", params)
        return cur.fetchone()["c"]


# ===== Core: apply transaction =====
def apply_transaction(
    user_id: str,
    type: str,
    amount: float,
    affects_balance: bool = True,
    trip_id: Optional[str] = None,
    description: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    """يستدعي دالة SQL wallet_apply_transaction. يرجع dict."""
    try:
        with db_cursor(dict_cursor=True) as cur:
            cur.execute(
                """
                SELECT * FROM wallet_apply_transaction(
                    %s::uuid, %s::varchar, %s::numeric, %s::boolean,
                    %s::uuid, %s::text, %s::varchar, %s::uuid, %s::uuid
                )
                """,
                (
                    user_id, type, amount, affects_balance,
                    trip_id, description, reference_type, reference_id, created_by,
                ),
            )
            row = cur.fetchone()

        if not row:
            return {"success": False, "error_message": "فشل غير معروف"}

        return {
            "success": row["success"],
            "error_message": row.get("error_message"),
            "transaction_id": str(row["transaction_id"]) if row.get("transaction_id") else None,
            "new_balance": float(row["new_balance"]) if row.get("new_balance") is not None else None,
        }
    except Exception as e:
        logger.exception(f"apply_transaction failed: {e}")
        return {"success": False, "error_message": str(e)}


# ===== Helpers عالية المستوى =====
def deposit(user_id: str, amount: float, admin_id: Optional[str] = None,
            description: Optional[str] = None) -> dict:
    return apply_transaction(
        user_id=user_id,
        type="deposit",
        amount=amount,
        affects_balance=True,
        description=description or "إيداع",
        reference_type="admin" if admin_id else "system",
        created_by=admin_id,
    )


def withdraw(user_id: str, amount: float, admin_id: Optional[str] = None,
             description: Optional[str] = None) -> dict:
    return apply_transaction(
        user_id=user_id,
        type="withdraw",
        amount=-abs(amount),
        affects_balance=True,
        description=description or "سحب",
        reference_type="admin" if admin_id else "system",
        created_by=admin_id,
    )


def adjust(user_id: str, amount: float, admin_id: str, description: str) -> dict:
    """تعديل إداري (موجب أو سالب)."""
    return apply_transaction(
        user_id=user_id,
        type="adjustment",
        amount=amount,
        affects_balance=True,
        description=description,
        reference_type="admin",
        created_by=admin_id,
    )


def charge_commission(user_id: str, trip_id: str, price: float) -> dict:
    """يخصم عمولة الرحلة من محفظة السائق."""
    try:
        with db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT calculate_commission(%s) AS c", (price,))
            commission = float(cur.fetchone()["c"])

        if commission <= 0:
            return {"success": True, "commission": 0, "new_balance": None}

        result = apply_transaction(
            user_id=user_id,
            type="commission",
            amount=-commission,
            affects_balance=True,
            trip_id=trip_id,
            description=f"عمولة المنصة عن رحلة بقيمة {price:.2f}",
            reference_type="trip",
            reference_id=trip_id,
        )
        result["commission"] = commission
        return result
    except Exception as e:
        logger.exception(f"charge_commission failed: {e}")
        return {"success": False, "error_message": str(e), "commission": 0}


# ===== Business checks =====
def can_go_online(user_id: str) -> tuple[bool, str]:
    """يتحقق إذا السائق عنده رصيد كافي."""
    min_balance = settings.get_float("wallet.min_balance_to_go_online", 0)

    w = get_wallet(user_id)
    if not w:
        return False, "المحفظة غير موجودة"

    if w["is_locked"]:
        return False, f"المحفظة مقفلة: {w.get('lock_reason') or 'بدون سبب'}"

    if w["balance"] < min_balance:
        return False, f"الرصيد غير كافٍ (المطلوب {min_balance}، لديك {w['balance']})"

    return True, ""


def lock_wallet(user_id: str, reason: str, admin_id: str) -> bool:
    try:
        with db_cursor() as cur:
            cur.execute(
                "UPDATE wallets SET is_locked = TRUE, lock_reason = %s WHERE user_id = %s",
                (reason, user_id),
            )
        return True
    except Exception as e:
        logger.exception(f"lock_wallet failed: {e}")
        return False


def unlock_wallet(user_id: str) -> bool:
    try:
        with db_cursor() as cur:
            cur.execute(
                "UPDATE wallets SET is_locked = FALSE, lock_reason = NULL WHERE user_id = %s",
                (user_id,),
            )
        return True
    except Exception as e:
        logger.exception(f"unlock_wallet failed: {e}")
        return False