#!/bin/sh
set -e

# Проверяем, существует ли таблица alembic_version (признак существующей БД).
# Если да — применяем миграции. Если нет — свежая БД, create_all + stamp сделает всё сам.
echo "⏳ Checking database state..."
HAS_ALEMBIC=$(python -c "
import sys
from app.config import settings
url = settings.DATABASE_URL.replace('+asyncpg', '')
from sqlalchemy import create_engine, inspect
try:
    eng = create_engine(url)
    with eng.connect() as c:
        tables = inspect(c).get_table_names()
    eng.dispose()
    print('yes' if 'alembic_version' in tables else 'no')
except Exception:
    print('no')
" 2>/dev/null || echo "no")

if [ "$HAS_ALEMBIC" = "yes" ]; then
    echo "📦 Existing DB detected, running Alembic migrations..."
    alembic upgrade head
else
    echo "🆕 Fresh or unmanaged DB — app will create tables on startup"
fi

echo "🚀 Starting application..."
exec python main.py
