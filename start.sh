#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

PORT="${1:-8000}"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv || python -m venv .venv
    ./.venv/bin/pip install -r requirements.lock
fi

./.venv/bin/python manage.py migrate

if [ ! -f "db.sqlite3" ]; then
    echo "Building initial database content..."
    ./.venv/bin/python manage.py seed_demo
    ./.venv/bin/python manage.py import_dorar_pilot --apply
    ./.venv/bin/python manage.py enrich_medina --apply
    ./.venv/bin/python manage.py enrich_stories --apply
    ./.venv/bin/python manage.py complete_journey --apply
fi

echo ""
echo "========================================================"
echo "              منصة أثَر | ATHAR PLATFORM                "
echo "========================================================"
echo "  رابط المنصة:     http://127.0.0.1:$PORT/"
echo "  لوحة الإدارة:    http://127.0.0.1:$PORT/dashboard/"
echo "  المستخدم:        admin"
echo "  كلمة المرور:     admin123456"
echo "========================================================"
echo ""

./.venv/bin/python manage.py runserver "127.0.0.1:$PORT"
