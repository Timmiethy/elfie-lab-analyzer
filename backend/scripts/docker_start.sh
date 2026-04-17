#!/usr/bin/env sh
set -eu

echo "[docker_start] Running Alembic migrations..."
python -m alembic upgrade head

echo "[docker_start] Starting backend at http://0.0.0.0:8000"
exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
