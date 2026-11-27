#!/bin/bash
# ============================================================
# Taxi App — Project Structure Setup
# Run from: ~/taxi_app
# ============================================================

set -e

# تأكد إننا في المجلد الصح
if [ ! -d "venv" ] && [ ! -f ".env" ]; then
    echo "⚠️  تنبيه: مش شايف venv ولا .env — تأكد إنك داخل ~/taxi_app"
fi

# ============================================================
# 1) إنشاء المجلدات
# ============================================================
mkdir -p app/core
mkdir -p app/models
mkdir -p app/routers
mkdir -p app/realtime
mkdir -p app/services
mkdir -p scripts

# ============================================================
# 2) ملفات __init__.py
# ============================================================
touch app/__init__.py
touch app/core/__init__.py
touch app/models/__init__.py
touch app/routers/__init__.py
touch app/realtime/__init__.py
touch app/services/__init__.py

# ============================================================
# 3) ملفات core
# ============================================================
touch app/core/config.py
touch app/core/database.py
touch app/core/security.py
touch app/core/deps.py

# ============================================================
# 4) ملفات models
# ============================================================
touch app/models/auth.py
touch app/models/user.py
touch app/models/driver.py
touch app/models/trip.py
touch app/models/rating.py

# ============================================================
# 5) ملفات routers
# ============================================================
touch app/routers/auth.py
touch app/routers/users.py
touch app/routers/drivers.py
touch app/routers/trips.py
touch app/routers/locations.py
touch app/routers/ratings.py
touch app/routers/admin.py

# ============================================================
# 6) ملفات realtime
# ============================================================
touch app/realtime/manager.py
touch app/realtime/ws.py

# ============================================================
# 7) ملفات services
# ============================================================
touch app/services/pricing.py
touch app/services/matching.py
touch app/services/trip_service.py
touch app/services/notifications.py

# ============================================================
# 8) ملفات الجذر
# ============================================================
touch app/main.py
touch requirements.txt
touch README.md
touch .gitignore
touch .env
touch .env.example
touch scripts/taxi_schema.sql
touch scripts/seed_data.py

# ============================================================
# 9) محتوى .gitignore
# ============================================================
cat > .gitignore <<'EOF'
venv/
.venv/
__pycache__/
*.pyc
*.pyo
*.log
.env
.DS_Store
.idea/
.vscode/
EOF

# ============================================================
# 10) محتوى .env
# ============================================================
cat > .env <<'EOF'
# ===== Database =====
DB_NAME=taxi_app
DB_USER=postgres
DB_PASSWORD=123
DB_HOST=localhost
DB_PORT=5432

# ===== JWT =====
SECRET_KEY=8f3a2b9c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a
REFRESH_SECRET_KEY=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30

# ===== App =====
APP_HOST=0.0.0.0
APP_PORT=7070
DEBUG=true
CORS_ORIGINS=*
EOF

# ============================================================
# 11) محتوى .env.example (نفسه بدون أسرار)
# ============================================================
cat > .env.example <<'EOF'
# ===== Database =====
DB_NAME=taxi_app
DB_USER=postgres
DB_PASSWORD=changeme
DB_HOST=localhost
DB_PORT=5432

# ===== JWT =====
SECRET_KEY=change-me
REFRESH_SECRET_KEY=change-me-too
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30

# ===== App =====
APP_HOST=0.0.0.0
APP_PORT=7070
DEBUG=true
CORS_ORIGINS=*
EOF

# ============================================================
# 12) محتوى requirements.txt
# ============================================================
cat > requirements.txt <<'EOF'
fastapi==0.115.0
uvicorn[standard]==0.32.0
psycopg2-binary==2.9.9
python-jose[cryptography]==3.3.0
pydantic==2.9.2
pydantic-settings==2.5.2
python-dotenv==1.0.1
python-multipart==0.0.12
websockets==13.1
EOF

echo ""
echo "✅ الهيكل جاهز!"
echo ""
echo "📁 الهيكل:"
find app -type f | sort
echo ""
echo "📄 ملفات الجذر:"
ls -1 .env .env.example .gitignore requirements.txt README.md 2>/dev/null
echo ""
echo "🚀 الخطوة التالية:"
echo "  1) source venv/bin/activate"
echo "  2) pip install -r requirements.txt"
echo "  3) اكتب محتوى الملفات الأساسية (config.py, database.py, ...)"
echo "  4) uvicorn app.main:app --reload --host 0.0.0.0 --port 7070"