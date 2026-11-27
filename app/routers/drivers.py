"""
Drivers Router
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg2 import errors

from app.core.database import db_cursor
from app.core.deps import get_current_user, require_role
from app.models.driver import (
    DocumentResponse,
    DocumentUploadRequest,
    DocumentWithImageResponse,
    DriverMeResponse,
    LocationUpdateRequest,
    NearbyDriver,
    VehicleUpdateRequest,
)
from app.services import wallet as wallet_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== Helpers =====
def _fetch_driver_me(cur, user_id: str) -> dict | None:
    cur.execute(
        """
        SELECT
            d.user_id, d.car_model, d.car_plate, d.car_color, d.car_year, d.car_type,
            d.account_status, d.account_status_note, d.availability_status,
            d.current_lat, d.current_lng, d.last_location_at,
            d.rating_avg, d.rating_count, d.total_trips, d.wallet_balance,
            u.phone, u.full_name, u.email
        FROM drivers d
        JOIN users u ON u.id = d.user_id
        WHERE d.user_id = %s
        """,
        (user_id,),
    )
    row = cur.fetchone()

    if not row:
        return None

    cur.execute(
        """
        SELECT doc_type, mime_type, uploaded_at, updated_at
        FROM driver_documents
        WHERE driver_id = %s
        ORDER BY doc_type
        """,
        (user_id,),
    )
    docs = cur.fetchall()

    return {
        **row,
        "documents": [
            DocumentResponse(
                doc_type=r["doc_type"],
                mime_type=r["mime_type"],
                uploaded_at=r["uploaded_at"].isoformat(),
                updated_at=r["updated_at"].isoformat(),
            )
            for r in docs
        ],
    }


# ===== GET /me =====
@router.get("/me", response_model=DriverMeResponse, summary="بيانات السائق الحالي")
async def get_me(user: dict = Depends(require_role("driver"))):
    with db_cursor(dict_cursor=True) as cur:
        row = _fetch_driver_me(cur, user["sub"])

    if not row:
        raise HTTPException(status_code=404, detail="ملف السائق غير موجود")

    return DriverMeResponse(
        user_id=str(row["user_id"]),
        phone=row["phone"],
        full_name=row["full_name"],
        email=row.get("email"),
        car_model=row["car_model"],
        car_plate=row["car_plate"],
        car_color=row.get("car_color"),
        car_year=row.get("car_year"),
        car_type=row["car_type"],
        account_status=row["account_status"],
        account_status_note=row.get("account_status_note"),
        availability_status=row["availability_status"],
        current_lat=row.get("current_lat"),
        current_lng=row.get("current_lng"),
        last_location_at=row["last_location_at"].isoformat() if row.get("last_location_at") else None,
        rating_avg=float(row["rating_avg"]),
        rating_count=row["rating_count"],
        total_trips=row["total_trips"],
        wallet_balance=float(row["wallet_balance"]),
        documents=row["documents"],
    )


# ===== PUT /me/vehicle =====
@router.put("/me/vehicle", summary="تحديث بيانات السيارة")
async def update_vehicle(
    data: VehicleUpdateRequest,
    user: dict = Depends(require_role("driver")),
):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="لا يوجد بيانات للتحديث")

    set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
    values = list(updates.values()) + [user["sub"]]

    try:
        with db_cursor() as cur:
            cur.execute(
                f"UPDATE drivers SET {set_clause} WHERE user_id = %s",
                values,
            )
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="رقم اللوحة مستخدم بالفعل")

    return {"status": "success", "updated_fields": list(updates.keys())}


# ===== POST /me/documents =====
@router.post(
    "/me/documents",
    summary="رفع مستند (base64) — حد أقصى 2MB",
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    data: DocumentUploadRequest,
    user: dict = Depends(require_role("driver")),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            INSERT INTO driver_documents (driver_id, doc_type, image_base64, mime_type)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (driver_id, doc_type)
            DO UPDATE SET
                image_base64 = EXCLUDED.image_base64,
                mime_type = EXCLUDED.mime_type,
                updated_at = NOW()
            RETURNING doc_type, mime_type, uploaded_at, updated_at
            """,
            (user["sub"], data.doc_type, data.image_base64, data.mime_type),
        )
        row = cur.fetchone()

    return {
        "status": "success",
        "document": DocumentResponse(
            doc_type=row["doc_type"],
            mime_type=row["mime_type"],
            uploaded_at=row["uploaded_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        ),
    }


# ===== GET /me/documents =====
@router.get(
    "/me/documents",
    response_model=list[DocumentResponse],
    summary="قائمة مستندات السائق (بدون الصور)",
)
async def list_documents(user: dict = Depends(require_role("driver"))):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT doc_type, mime_type, uploaded_at, updated_at
            FROM driver_documents
            WHERE driver_id = %s
            ORDER BY doc_type
            """,
            (user["sub"],),
        )
        rows = cur.fetchall()

    return [
        DocumentResponse(
            doc_type=r["doc_type"],
            mime_type=r["mime_type"],
            uploaded_at=r["uploaded_at"].isoformat(),
            updated_at=r["updated_at"].isoformat(),
        )
        for r in rows
    ]


# ===== GET /me/documents/{doc_type} =====
@router.get(
    "/me/documents/{doc_type}",
    response_model=DocumentWithImageResponse,
    summary="جلب مستند محدد مع الصورة",
)
async def get_document(doc_type: str, user: dict = Depends(require_role("driver"))):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT doc_type, image_base64, mime_type, uploaded_at, updated_at
            FROM driver_documents
            WHERE driver_id = %s AND doc_type = %s
            """,
            (user["sub"], doc_type),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="المستند غير موجود")

    return DocumentWithImageResponse(
        doc_type=row["doc_type"],
        image_base64=row["image_base64"],
        mime_type=row["mime_type"],
        uploaded_at=row["uploaded_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


# ===== DELETE /me/documents/{doc_type} =====
@router.delete("/me/documents/{doc_type}", summary="حذف مستند")
async def delete_document(doc_type: str, user: dict = Depends(require_role("driver"))):
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM driver_documents WHERE driver_id = %s AND doc_type = %s",
            (user["sub"], doc_type),
        )
        deleted = cur.rowcount

    if deleted == 0:
        raise HTTPException(status_code=404, detail="المستند غير موجود")

    return {"status": "success", "deleted": doc_type}


# ===== POST /me/online =====
@router.post("/me/online", summary="السائق يصير متاح")
async def go_online(user: dict = Depends(require_role("driver"))):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT account_status, availability_status FROM drivers WHERE user_id = %s",
            (user["sub"],),
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="ملف السائق غير موجود")

        if row["account_status"] != "approved":
            raise HTTPException(
                status_code=403,
                detail=f"الحساب بحالة '{row['account_status']}' — لازم يكون approved",
            )

        if row["availability_status"] == "on_trip":
            raise HTTPException(status_code=409, detail="السائق حالياً برحلة")

    # تحقق من رصيد المحفظة
    can_online, wallet_msg = wallet_service.can_go_online(user["sub"])
    if not can_online:
        raise HTTPException(status_code=403, detail=wallet_msg)

    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE drivers
            SET availability_status = 'online',
                availability_changed_at = NOW()
            WHERE user_id = %s
            """,
            (user["sub"],),
        )

    return {"status": "success", "availability_status": "online"}


# ===== POST /me/offline =====
@router.post("/me/offline", summary="السائق يصير غير متاح")
async def go_offline(user: dict = Depends(require_role("driver"))):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT availability_status FROM drivers WHERE user_id = %s",
            (user["sub"],),
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="ملف السائق غير موجود")

        if row["availability_status"] == "on_trip":
            raise HTTPException(status_code=409, detail="ما يقدر يصير offline وهو برحلة")

        cur.execute(
            """
            UPDATE drivers
            SET availability_status = 'offline',
                availability_changed_at = NOW()
            WHERE user_id = %s
            """,
            (user["sub"],),
        )

    return {"status": "success", "availability_status": "offline"}


# ===== POST /me/location =====
@router.post("/me/location", summary="تحديث موقع السائق")
async def update_location(
    data: LocationUpdateRequest,
    user: dict = Depends(require_role("driver")),
):
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE drivers
            SET current_lat = %s,
                current_lng = %s,
                current_location = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                last_location_at = NOW()
            WHERE user_id = %s
            """,
            (data.lat, data.lng, data.lng, data.lat, user["sub"]),
        )

    return {"status": "success", "lat": data.lat, "lng": data.lng}


# ===== GET /nearby =====
@router.get(
    "/nearby",
    response_model=list[NearbyDriver],
    summary="أقرب السائقين المتاحين",
)
async def nearby_drivers(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_meters: int = Query(5000, ge=100, le=50000),
    limit: int = Query(10, ge=1, le=50),
    car_type: str | None = Query(None),
    _user: dict = Depends(get_current_user),
):
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT * FROM find_nearby_drivers(%s, %s, %s, %s, %s)
            """,
            (lat, lng, radius_meters, limit, car_type),
        )
        rows = cur.fetchall()

    return [
        NearbyDriver(
            driver_id=str(r["driver_id"]),
            full_name=r["full_name"],
            car_model=r["car_model"],
            car_plate=r["car_plate"],
            car_color=r.get("car_color"),
            car_type=r.get("car_type", "sedan"),
            rating_avg=float(r["rating_avg"]),
            distance_meters=float(r["distance_meters"]),
            lat=float(r["lat"]),
            lng=float(r["lng"]),
        )
        for r in rows
    ]