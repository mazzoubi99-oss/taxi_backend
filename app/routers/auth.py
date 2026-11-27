"""
Auth Router — register / login / refresh / me
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2 import errors

from app.core.config import settings
from app.core.database import db_cursor
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.auth import (
    LoginRequest,
    ProfileUpdateRequest,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import notifications as notif

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== Helpers =====
def _row_to_user(row: dict) -> UserResponse:
    return UserResponse(
        id=str(row["id"]),
        phone=row["phone"],
        full_name=row["full_name"],
        email=row.get("email"),
        role=row["role"],
        is_active=row["is_active"],
        is_verified=row["is_verified"],
        avatar_url=row.get("avatar_url"),
        language=row.get("language", "ar"),
    )


def _build_token_payload(user_row: dict) -> dict:
    return {
        "sub": str(user_row["id"]),
        "phone": user_row["phone"],
        "role": user_row["role"],
        "name": user_row["full_name"],
    }


# ===== POST /register =====
@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="تسجيل مستخدم جديد (راكب أو سائق)",
)
async def register(data: RegisterRequest):
    hashed = hash_password(data.password)

    try:
        with db_cursor(dict_cursor=True) as cur:
            cur.execute(
                """
                INSERT INTO users (phone, full_name, email, password_hash, role)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, phone, full_name, email, role,
                          is_active, is_verified, avatar_url, language
                """,
                (data.phone, data.full_name, data.email, hashed, data.role),
            )
            user_row = cur.fetchone()

            # إذا سائق → ننشئ صف مبدئي في drivers (البيانات تكمل لاحقاً)
            if data.role == "driver":
                cur.execute(
                    """
                    INSERT INTO drivers (user_id, car_model, car_plate)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        user_row["id"],
                        "غير محدد",
                        f"TEMP-{str(user_row['id'])[:8]}",
                    ),
                )
    except errors.UniqueViolation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="رقم الهاتف أو الإيميل مستخدم بالفعل",
        )
    except Exception as e:
        logger.exception(f"Register error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # ===== إشعار الأدمن بسائق جديد =====
    if data.role == "driver":
        try:
            notif.notify_admins_new_driver(
                driver_id=str(user_row["id"]),
                driver_name=user_row["full_name"],
                phone=user_row["phone"],
            )
        except Exception as e:
            # ما نكسر التسجيل لو الإشعار فشل
            logger.error(f"notify_admins_new_driver failed: {e}")

    payload = _build_token_payload(user_row)
    access = create_access_token(payload)
    refresh = create_refresh_token(payload)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_row_to_user(user_row),
    )


# ===== POST /login =====
@router.post("/login", response_model=TokenResponse, summary="تسجيل الدخول")
async def login(data: LoginRequest):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT id, phone, full_name, email, role,
                   is_active, is_verified, avatar_url, language,
                   password_hash
            FROM users
            WHERE phone = %s
            LIMIT 1
            """,
            (data.phone,),
        )
        user_row = cur.fetchone()

    if not user_row or not verify_password(data.password, user_row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="رقم الهاتف أو كلمة المرور غير صحيحة",
        )

    if not user_row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="الحساب موقوف",
        )

    # تحديث last_login_at
    with db_cursor() as cur:
        cur.execute(
            "UPDATE users SET last_login_at = %s WHERE id = %s",
            (datetime.utcnow(), user_row["id"]),
        )

    payload = _build_token_payload(user_row)
    access = create_access_token(payload)
    refresh = create_refresh_token(payload)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_row_to_user(user_row),
    )


# ===== POST /refresh =====
@router.post("/refresh", response_model=RefreshResponse, summary="تجديد التوكن")
async def refresh_token(data: RefreshRequest):
    payload = decode_token(data.refresh_token, token_type="refresh")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token غير صالح أو منتهي",
        )

    # تأكد إن المستخدم لسا موجود ونشط
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT id, phone, full_name, role, is_active FROM users WHERE id = %s",
            (payload["sub"],),
        )
        user_row = cur.fetchone()

    if not user_row or not user_row["is_active"]:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود أو موقوف")

    new_access = create_access_token(_build_token_payload(user_row))

    return RefreshResponse(
        access_token=new_access,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ===== GET /me =====
@router.get("/me", response_model=UserResponse, summary="معلومات المستخدم الحالي")
async def me(user: dict = Depends(get_current_user)):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT id, phone, full_name, email, role,
                   is_active, is_verified, avatar_url, language
            FROM users WHERE id = %s
            """,
            (user["sub"],),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")

    return _row_to_user(row)

@router.put("/me", response_model=UserResponse, summary="تعديل الاسم الشخصي")
def update_profile(data: ProfileUpdateRequest, user: dict = Depends(get_current_user)):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            UPDATE users SET full_name = %s
            WHERE id = %s AND is_active = TRUE
            RETURNING id, phone, full_name, email, role, is_active, is_verified,
                      avatar_url, language
            """,
            (data.full_name, user["sub"]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return _row_to_user(row)
