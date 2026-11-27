"""
اتصال قاعدة البيانات + context manager آمن
"""
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2 import extras

from app.core.config import settings

logger = logging.getLogger(__name__)



def get_connection():
    conn = psycopg2.connect(settings.db_dsn)
    conn.autocommit = True
    return conn


def get_connection_tx():
    """اتصال بدون autocommit — للـ transactions اليدوية."""
    conn = psycopg2.connect(settings.db_dsn)
    conn.autocommit = False
    return conn

@contextmanager
def db_cursor(dict_cursor: bool = False):
    """
    context manager للاستخدام الآمن:
        with db_cursor() as cur:
            cur.execute(...)
    """
    conn = get_connection()
    try:
        factory = extras.RealDictCursor if dict_cursor else None
        with conn.cursor(cursor_factory=factory) as cur:
            yield cur
    finally:
        conn.close()


def check_db() -> bool:
    """تحقق سريع إن الداتابيز شغالة."""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"DB check failed: {e}")
        return False