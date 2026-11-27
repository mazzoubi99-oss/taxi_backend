"""
Settings service — قراءة/كتابة app_settings مع cache
"""
import logging
import time
from typing import Any, Optional

from app.core.database import db_cursor

logger = logging.getLogger(__name__)

# ===== Cache =====
_CACHE: dict[str, tuple[Any, float]] = {}
_CACHE_TTL_SECONDS = 60


def _cache_get(key: str) -> Optional[Any]:
    if key in _CACHE:
        value, expires_at = _CACHE[key]
        if time.time() < expires_at:
            return value
        del _CACHE[key]
    return None


def _cache_set(key: str, value: Any):
    _CACHE[key] = (value, time.time() + _CACHE_TTL_SECONDS)


def _cache_clear(key: Optional[str] = None):
    if key:
        _CACHE.pop(key, None)
    else:
        _CACHE.clear()


# ===== Read =====
def get_setting(key: str, default: Any = None) -> Any:
    """يقرأ إعداد. بيرجع الـ JSONB value كـ Python object."""
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        with db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
            row = cur.fetchone()

        if not row:
            return default

        value = row["value"]
        _cache_set(key, value)
        return value
    except Exception as e:
        logger.error(f"get_setting({key}) failed: {e}")
        return default


def get_int(key: str, default: int = 0) -> int:
    v = get_setting(key, default)
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def get_float(key: str, default: float = 0.0) -> float:
    v = get_setting(key, default)
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    v = get_setting(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() == "true"
    return default


def get_str(key: str, default: str = "") -> str:
    v = get_setting(key, default)
    if v is None:
        return default
    return str(v)


def get_category(category: str) -> dict[str, Any]:
    """كل إعدادات قسم معين."""
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT key, value FROM app_settings WHERE category = %s ORDER BY key",
            (category,),
        )
        rows = cur.fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_all() -> list[dict]:
    """كل الإعدادات (للأدمن)."""
    with db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """
            SELECT key, value, description, category, updated_at
            FROM app_settings ORDER BY category, key
            """
        )
        rows = cur.fetchall()

    return [
        {
            "key": r["key"],
            "value": r["value"],
            "description": r["description"],
            "category": r["category"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


# ===== Write =====
def set_setting(key: str, value: Any, updated_by: Optional[str] = None) -> bool:
    """يعدّل إعداد موجود. يرجع True/False."""
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                UPDATE app_settings
                SET value = %s::jsonb, updated_by = %s, updated_at = NOW()
                WHERE key = %s
                """,
                (_to_json(value), updated_by, key),
            )
            if cur.rowcount == 0:
                return False
        _cache_clear(key)
        return True
    except Exception as e:
        logger.error(f"set_setting({key}) failed: {e}")
        return False


def set_settings_bulk(items: dict[str, Any], updated_by: Optional[str] = None) -> dict:
    """يعدّل عدة إعدادات. يرجع {updated: [...], not_found: [...]}."""
    updated = []
    not_found = []

    with db_cursor() as cur:
        for key, value in items.items():
            cur.execute(
                """
                UPDATE app_settings
                SET value = %s::jsonb, updated_by = %s, updated_at = NOW()
                WHERE key = %s
                """,
                (_to_json(value), updated_by, key),
            )
            if cur.rowcount > 0:
                updated.append(key)
            else:
                not_found.append(key)

    for key in updated:
        _cache_clear(key)

    return {"updated": updated, "not_found": not_found}


def invalidate_cache(key: Optional[str] = None):
    _cache_clear(key)


# ===== Helpers =====
def _to_json(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)