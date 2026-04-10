#!/usr/bin/env bash
set -euo pipefail

DB_USER="${ELFIE_DB_USER:-elfie}"
DB_PASS="${ELFIE_DB_PASS:-elfie}"
DB_NAME="${ELFIE_DB_NAME:-elfie_labs}"

echo "Creating database $DB_NAME..."
createdb -U "$DB_USER" "$DB_NAME" 2>/dev/null || echo "Database already exists"

echo "Running migrations..."
cd "$(dirname "$0")/../backend"
alembic upgrade head

echo "Done."
