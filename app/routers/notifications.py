"""
Notifications Router — للمستخدم
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import db_cursor
from app.core.deps import get_current_user
from app.models.notification import (
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _row_to_notification(row: dict) -> NotificationResponse:
    return NotificationResponse(
        id=str(row["id"]),
        type=row["type"],
        title=row["title"],
        body=row["body"],
        data=row.get("data"),
        sender_type=row["sender_type"],
        is_read=row["is_read"],
        created_at=row["created_at"].isoformat(),
        read_at=row["read_at"].isoformat() if row.get("read_at") else None,
    )


# ===== GET / =====
@router.get("", response_model=NotificationListResponse, summary="قائمة إشعاراتي")
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    with db_cursor(dict_cursor=True) as cur:
        where = "recipient_id = %s"
        params: list = [user["sub"]]

        if unread_only:
            where += " AND is_read = FALSE"

        cur.execute(
            f"""
            SELECT id, type, title, body, data, sender_type, is_read,
                   created_at, read_at
            FROM notifications
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

        cur.execute(
            f"SELECT COUNT(*) AS total FROM notifications WHERE {where}",
            params,
        )
        total = cur.fetchone()["total"]

        cur.execute(
            "SELECT COUNT(*) AS unread FROM notifications "
            "WHERE recipient_id = %s AND is_read = FALSE",
            (user["sub"],),
        )
        unread = cur.fetchone()["unread"]

    return NotificationListResponse(
        notifications=[_row_to_notification(r) for r in rows],
        total=total,
        unread=unread,
    )


# ===== GET /unread-count =====
@router.get("/unread-count", response_model=UnreadCountResponse, summary="عدد غير المقروء")
async def unread_count(user: dict = Depends(get_current_user)):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT COUNT(*) AS unread FROM notifications "
            "WHERE recipient_id = %s AND is_read = FALSE",
            (user["sub"],),
        )
        row = cur.fetchone()
    return UnreadCountResponse(unread=row["unread"])


# ===== POST /{id}/read =====
@router.post("/{notification_id}/read", summary="تعليم كمقروء")
async def mark_read(notification_id: str, user: dict = Depends(get_current_user)):
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE notifications
            SET is_read = TRUE, read_at = NOW()
            WHERE id = %s AND recipient_id = %s AND is_read = FALSE
            """,
            (notification_id, user["sub"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="الإشعار غير موجود أو مقروء مسبقاً")
    return {"status": "success"}


# ===== POST /read-all =====
@router.post("/read-all", summary="تعليم الكل كمقروء")
async def mark_all_read(user: dict = Depends(get_current_user)):
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE notifications
            SET is_read = TRUE, read_at = NOW()
            WHERE recipient_id = %s AND is_read = FALSE
            """,
            (user["sub"],),
        )
        count = cur.rowcount
    return {"status": "success", "marked": count}


# ===== DELETE /{id} =====
@router.delete("/{notification_id}", summary="حذف إشعار")
async def delete_notification(notification_id: str, user: dict = Depends(get_current_user)):
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM notifications WHERE id = %s AND recipient_id = %s",
            (notification_id, user["sub"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="الإشعار غير موجود")
    return {"status": "success"}