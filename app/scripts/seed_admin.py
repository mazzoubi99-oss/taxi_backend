"""
ينشئ أول أدمن في قاعدة البيانات.
الاستخدام (من جذر المشروع ~/taxi_app):
    python -m scripts.seed_admin
"""
import getpass
import sys

from app.core.database import db_cursor
from app.core.security import hash_password


def main():
    print("=" * 50)
    print("  إنشاء أول أدمن — Taxi App")
    print("=" * 50)

    phone = input("رقم الهاتف: ").strip()
    full_name = input("الاسم الكامل: ").strip()
    password = getpass.getpass("كلمة المرور: ")
    password2 = getpass.getpass("تأكيد كلمة المرور: ")

    if password != password2:
        print("❌ كلمتا المرور غير متطابقتين")
        sys.exit(1)

    if len(password) < 6:
        print("❌ كلمة المرور قصيرة (6 أحرف على الأقل)")
        sys.exit(1)

    with db_cursor(dict_cursor=True) as cur:
        # تأكد إنه ما في أدمن بنفس الرقم
        cur.execute("SELECT id FROM users WHERE phone = %s", (phone,))
        if cur.fetchone():
            print(f"❌ يوجد مستخدم بنفس الرقم: {phone}")
            sys.exit(1)

        cur.execute(
            """
            INSERT INTO users (phone, full_name, password_hash, role, is_verified)
            VALUES (%s, %s, %s, 'admin', TRUE)
            RETURNING id
            """,
            (phone, full_name, hash_password(password)),
        )
        user_id = cur.fetchone()["id"]

    print(f"✅ تم إنشاء الأدمن: {user_id}")
    print(f"   phone: {phone}")
    print(f"   name:  {full_name}")
    print("\nجرّب تسجيل الدخول عبر /api/auth/login")


if __name__ == "__main__":
    main()