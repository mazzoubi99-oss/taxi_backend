"""
Taxi App — نقطة الدخول.
تشغيل:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 7070
"""
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import check_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="Taxi App API",
    description="Backend لتطبيق تاكسي — سائق + راكب + لوحة تحكم",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ===== CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Imports =====
from app.routers import (
    # Auth + User
    auth,
    drivers,
    # Trips
    trips,
    # Wallet
    wallet,
    # Promo
    promo,
    # Notifications
    notifications,
    # Admin
    admin,
    admin_promo,
    admin_settings,
    admin_trips,
    admin_wallet,
    admin_dashboard,
    admin_riders,
    admin_priority_factors,
    admin_cancellation_reasons,
    admin_reports,
)
from app.realtime import ws as realtime_ws


# ===== Public Routers =====
app.include_router(auth.router,           prefix="/api/auth",          tags=["Auth"])
app.include_router(drivers.router,        prefix="/api/drivers",       tags=["Drivers"])
app.include_router(trips.router,          prefix="/api/trips",         tags=["Trips"])
app.include_router(wallet.router,         prefix="/api/wallet",        tags=["Wallet"])
app.include_router(promo.router,          prefix="/api/promo",         tags=["Promo"])
app.include_router(notifications.router,  prefix="/api/notifications", tags=["Notifications"])


# ===== Admin Routers =====
app.include_router(admin.router,                      prefix="/api/admin",                     tags=["Admin"])
app.include_router(admin_promo.router,                prefix="/api/admin/promo",               tags=["Admin - Promo"])
app.include_router(admin_settings.router,             prefix="/api/admin/settings",            tags=["Admin - Settings"])
app.include_router(admin_wallet.router,               prefix="/api/admin/wallet",              tags=["Admin - Wallet"])
app.include_router(admin_trips.router,                prefix="/api/admin/trips",               tags=["Admin - Trips"])
app.include_router(admin_dashboard.router,            prefix="/api/admin/dashboard",           tags=["Admin - Dashboard"])
app.include_router(admin_riders.router,               prefix="/api/admin/riders",              tags=["Admin - Riders"])
app.include_router(admin_priority_factors.router,     prefix="/api/admin/priority-factors",    tags=["Admin - Priority"])
app.include_router(admin_cancellation_reasons.router, prefix="/api/admin/cancellation-reasons", tags=["Admin - Reasons"])
app.include_router(admin_reports.router,              prefix="/api/admin/reports",             tags=["Admin - Reports"])


# ===== WebSocket =====
app.include_router(realtime_ws.router, tags=["WebSocket"])


# ===== Health & Root =====
@app.get("/", tags=["Root"])
async def root():
    return {"app": "Taxi App API", "version": "1.0.0", "status": "running"}


@app.get("/health", tags=["Health"])
async def health():
    db_ok = check_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
    }


# ===== Background Tasks =====
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_expire_loop())


async def _expire_loop():
    from app.services import dispatch
    while True:
        try:
            result = dispatch.expire_and_notify()
            if result["offers_expired"] or result["trips_expired"]:
                logger.info(f"Expired: {result}")
        except Exception as e:
            logger.error(f"expire_loop error: {e}")
        await asyncio.sleep(10)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )