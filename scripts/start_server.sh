#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

BACKEND_HOST="${ELFIE_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${ELFIE_BACKEND_PORT:-8000}"
FRONTEND_HOST="${ELFIE_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${ELFIE_FRONTEND_PORT:-5173}"

BOOTSTRAP_BACKEND="${ELFIE_BOOTSTRAP_BACKEND:-1}"
DB_PROVIDER="${ELFIE_DB_PROVIDER:-docker}"
DB_WAIT_TIMEOUT="${ELFIE_DB_WAIT_TIMEOUT:-120}"
RUN_MIGRATIONS="${ELFIE_RUN_MIGRATIONS:-1}"
AUTO_NPM_INSTALL="${ELFIE_AUTO_NPM_INSTALL:-1}"
ALEMBIC_AUTO_RECOVER_MISSING_REVISION="${ELFIE_ALEMBIC_AUTO_RECOVER_MISSING_REVISION:-}"
DB_USER="${ELFIE_DB_USER:-elfie}"
DB_NAME="${ELFIE_DB_NAME:-elfie_labs}"

MODE="${1:-all}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [all|backend|frontend]

Starts local dev servers with fixed host/port defaults:
  backend  -> ${BACKEND_HOST}:${BACKEND_PORT}
  frontend -> ${FRONTEND_HOST}:${FRONTEND_PORT}

Default end-to-end behavior for modes 'all' and 'backend':
  1) Load ${ROOT_DIR}/.env if present
  2) Start DB dependency (docker compose) when ELFIE_DB_PROVIDER=docker
  3) Run Alembic migrations
  4) Start selected server(s)

Optional environment overrides:
  ELFIE_BACKEND_HOST
  ELFIE_BACKEND_PORT
  ELFIE_FRONTEND_HOST
  ELFIE_FRONTEND_PORT
  ELFIE_BOOTSTRAP_BACKEND=1|0
  ELFIE_DB_PROVIDER=docker|external
  ELFIE_DB_WAIT_TIMEOUT=120
  ELFIE_RUN_MIGRATIONS=1|0
  ELFIE_AUTO_NPM_INSTALL=1|0
  ELFIE_ALEMBIC_AUTO_RECOVER_MISSING_REVISION=1|0
    (default: auto-recover for docker DB provider, strict for external DB)
  ELFIE_DB_USER / ELFIE_DB_NAME
    (used by docker-local alembic metadata recovery)
EOF
}

load_env_file() {
  local env_file
  env_file="${ROOT_DIR}/.env"

  if [[ -f "${env_file}" ]]; then
    # Export variables from .env for subprocesses (alembic, uvicorn, npm).
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a
  fi
}

find_python() {
  if [[ -x "${ROOT_DIR}/.venv/Scripts/python.exe" ]]; then
    printf "%s" "${ROOT_DIR}/.venv/Scripts/python.exe"
    return 0
  fi

  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    printf "%s" "${ROOT_DIR}/.venv/bin/python"
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi

  echo "Could not find a Python executable. Activate your environment first." >&2
  exit 1
}

ensure_docker_db() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required when ELFIE_DB_PROVIDER=docker. Install Docker or set ELFIE_DB_PROVIDER=external." >&2
    exit 1
  fi

  echo "Starting database dependency via docker compose..."
  (
    cd "${ROOT_DIR}"
    docker compose up -d db
  )

  wait_for_db_health
}

wait_for_db_health() {
  local container_id
  local elapsed
  local status

  container_id="$(cd "${ROOT_DIR}" && docker compose ps -q db)"
  if [[ -z "${container_id}" ]]; then
    echo "Could not locate the db container after docker compose up." >&2
    exit 1
  fi

  elapsed=0
  while (( elapsed < DB_WAIT_TIMEOUT )); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}" 2>/dev/null || true)"

    if [[ "${status}" == "healthy" || "${status}" == "running" ]]; then
      echo "Database is ready (status=${status})."
      return 0
    fi

    if [[ "${status}" == "unhealthy" || "${status}" == "exited" || "${status}" == "dead" ]]; then
      echo "Database container entered a bad state (${status})." >&2
      exit 1
    fi

    sleep 2
    elapsed=$((elapsed + 2))
  done

  echo "Timed out waiting for database readiness after ${DB_WAIT_TIMEOUT}s." >&2
  exit 1
}

should_auto_recover_missing_revision() {
  if [[ -n "${ALEMBIC_AUTO_RECOVER_MISSING_REVISION}" ]]; then
    [[ "${ALEMBIC_AUTO_RECOVER_MISSING_REVISION}" == "1" ]]
    return $?
  fi

  [[ "${DB_PROVIDER}" == "docker" ]]
}

reset_alembic_version_for_docker_db() {
  local python_cmd
  local head_revision
  python_cmd="$1"

  head_revision="$(
    cd "${ROOT_DIR}/backend"
    "${python_cmd}" -m alembic heads 2>/dev/null | awk 'NR==1 {print $1}'
  )"

  if [[ -z "${head_revision}" ]]; then
    echo "Failed to resolve current Alembic head revision from repository." >&2
    return 1
  fi

  echo "Repairing alembic_version metadata in docker DB to ${head_revision}..."
  (
    cd "${ROOT_DIR}"
    docker compose exec -T db psql -U "${DB_USER}" -d "${DB_NAME}" \
      -c "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL);"
    docker compose exec -T db psql -U "${DB_USER}" -d "${DB_NAME}" \
      -c "DELETE FROM alembic_version; INSERT INTO alembic_version(version_num) VALUES ('${head_revision}');"
  )
}

run_migrations() {
  local python_cmd
  local migration_output
  local migration_status
  local stamp_output
  local stamp_status
  python_cmd="$(find_python)"

  echo "Running Alembic migrations..."

  set +e
  migration_output="$(
    cd "${ROOT_DIR}/backend"
    "${python_cmd}" -m alembic upgrade head 2>&1
  )"
  migration_status=$?
  set -e

  if [[ "${migration_status}" -eq 0 ]]; then
    if [[ -n "${migration_output}" ]]; then
      printf "%s\n" "${migration_output}"
    fi
    return 0
  fi

  printf "%s\n" "${migration_output}" >&2

  if [[ "${migration_output}" == *"Can't locate revision identified by"* ]]; then
    if should_auto_recover_missing_revision; then
      echo "Detected stale Alembic revision metadata. Auto-recovering by stamping to repo head..."

      set +e
      stamp_output="$(
        cd "${ROOT_DIR}/backend"
        "${python_cmd}" -m alembic stamp head 2>&1
      )"
      stamp_status=$?
      set -e

      if [[ "${stamp_status}" -ne 0 ]]; then
        printf "%s\n" "${stamp_output}" >&2
        if [[ "${DB_PROVIDER}" == "docker" ]]; then
          reset_alembic_version_for_docker_db "${python_cmd}"
        else
          return "${stamp_status}"
        fi
      fi

      (
        cd "${ROOT_DIR}/backend"
        "${python_cmd}" -m alembic upgrade head
      )
      return 0
    fi

    echo "Set ELFIE_ALEMBIC_AUTO_RECOVER_MISSING_REVISION=1 to auto-recover missing Alembic revisions." >&2
  fi

  return "${migration_status}"
}

bootstrap_backend_stack() {
  load_env_file

  if [[ "${BOOTSTRAP_BACKEND}" != "1" ]]; then
    return 0
  fi

  if [[ "${DB_PROVIDER}" == "docker" ]]; then
    ensure_docker_db
  elif [[ "${DB_PROVIDER}" == "external" ]]; then
    echo "Skipping docker DB startup (ELFIE_DB_PROVIDER=external)."
  else
    echo "Unsupported ELFIE_DB_PROVIDER='${DB_PROVIDER}'. Use 'docker' or 'external'." >&2
    exit 1
  fi

  if [[ "${RUN_MIGRATIONS}" == "1" ]]; then
    run_migrations
  fi
}

start_backend() {
  local python_cmd
  python_cmd="$(find_python)"

  cd "${ROOT_DIR}"
  echo "Starting backend at http://${BACKEND_HOST}:${BACKEND_PORT}"
  "${python_cmd}" -m uvicorn backend.app.main:create_app \
    --factory \
    --host "${BACKEND_HOST}" \
    --port "${BACKEND_PORT}" \
    --reload
}

start_frontend() {
  if [[ "${AUTO_NPM_INSTALL}" == "1" && ! -d "${ROOT_DIR}/frontend/node_modules" ]]; then
    echo "Installing frontend dependencies (node_modules missing)..."
    (
      cd "${ROOT_DIR}/frontend"
      npm install
    )
  fi

  cd "${ROOT_DIR}/frontend"
  echo "Starting frontend at http://${FRONTEND_HOST}:${FRONTEND_PORT}"
  npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}"
}

if [[ "${MODE}" != "all" && "${MODE}" != "backend" && "${MODE}" != "frontend" ]]; then
  usage
  exit 1
fi

if [[ "${MODE}" == "backend" ]]; then
  bootstrap_backend_stack
  start_backend
  exit 0
fi

if [[ "${MODE}" == "frontend" ]]; then
  load_env_file
  start_frontend
  exit 0
fi

bootstrap_backend_stack

BACKEND_PID=""
cleanup() {
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    echo "Stopping backend (pid ${BACKEND_PID})"
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

python_cmd="$(find_python)"
cd "${ROOT_DIR}"
echo "Starting backend at http://${BACKEND_HOST}:${BACKEND_PORT}"
"${python_cmd}" -m uvicorn backend.app.main:create_app \
  --factory \
  --host "${BACKEND_HOST}" \
  --port "${BACKEND_PORT}" \
  --reload &
BACKEND_PID=$!

start_frontend
