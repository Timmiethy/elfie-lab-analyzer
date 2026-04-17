#!/usr/bin/env sh
set -eu

# Render's managed Postgres gives a `postgresql://` URL. Our async engine needs
# `postgresql+asyncpg://`. Rewrite scheme if needed so a single env var from
# Render works in both sync (alembic) + async (app) contexts.
if [ -n "${ELFIE_DATABASE_URL:-}" ]; then
  case "$ELFIE_DATABASE_URL" in
    postgresql://*)
      export ELFIE_DATABASE_URL="postgresql+asyncpg://${ELFIE_DATABASE_URL#postgresql://}"
      ;;
    postgres://*)
      export ELFIE_DATABASE_URL="postgresql+asyncpg://${ELFIE_DATABASE_URL#postgres://}"
      ;;
  esac
fi

# Sync URL is used by Alembic (psycopg2) — strip async driver if present.
if [ -n "${ELFIE_DATABASE_URL_SYNC:-}" ]; then
  case "$ELFIE_DATABASE_URL_SYNC" in
    postgresql+asyncpg://*)
      export ELFIE_DATABASE_URL_SYNC="postgresql://${ELFIE_DATABASE_URL_SYNC#postgresql+asyncpg://}"
      ;;
    postgres://*)
      export ELFIE_DATABASE_URL_SYNC="postgresql://${ELFIE_DATABASE_URL_SYNC#postgres://}"
      ;;
  esac
else
  # Derive sync URL from async URL if not provided
  if [ -n "${ELFIE_DATABASE_URL:-}" ]; then
    export ELFIE_DATABASE_URL_SYNC="postgresql://${ELFIE_DATABASE_URL#postgresql+asyncpg://}"
  fi
fi

echo "[docker_start] Running Alembic migrations..."
python -m alembic upgrade head

PORT="${PORT:-8000}"
echo "[docker_start] Starting backend at http://0.0.0.0:${PORT}"
exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT}"
