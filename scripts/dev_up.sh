#!/usr/bin/env bash
# dev_up.sh — kill any running local stack, then relaunch it fully.
# Ports (design-locked): backend=8000, frontend=5173, db=5432.
# Frontend vite proxy /api -> http://localhost:8000 (see frontend/vite.config.ts).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT_DIR}"

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="5173"
DB_PORT="5432"

LOG_DIR="${ROOT_DIR}/.devlogs"
mkdir -p "${LOG_DIR}"
BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"
BACKEND_PID_FILE="${LOG_DIR}/backend.pid"
FRONTEND_PID_FILE="${LOG_DIR}/frontend.pid"

is_windows() { [[ "${OS:-}" == "Windows_NT" ]] || [[ "$(uname -s 2>/dev/null)" == MINGW* ]] || [[ "$(uname -s 2>/dev/null)" == CYGWIN* ]] || [[ "$(uname -s 2>/dev/null)" == MSYS* ]]; }

kill_port() {
  local port="$1"
  echo "[kill] port ${port}"
  if is_windows; then
    # netstat + taskkill on Windows (Git Bash).
    local pids
    pids="$(netstat -ano 2>/dev/null | awk -v p=":${port}" '$2 ~ p && $4=="LISTENING" {print $5}' | sort -u || true)"
    if [[ -n "${pids}" ]]; then
      while IFS= read -r pid; do
        [[ -z "${pid}" ]] && continue
        echo "  taskkill pid=${pid}"
        taskkill //F //PID "${pid}" >/dev/null 2>&1 || true
      done <<< "${pids}"
    fi
  else
    if command -v lsof >/dev/null 2>&1; then
      local pids
      pids="$(lsof -ti tcp:"${port}" || true)"
      [[ -n "${pids}" ]] && kill -9 ${pids} >/dev/null 2>&1 || true
    elif command -v fuser >/dev/null 2>&1; then
      fuser -k "${port}"/tcp >/dev/null 2>&1 || true
    fi
  fi
}

kill_pid_file() {
  local f="$1"
  [[ -f "${f}" ]] || return 0
  local pid
  pid="$(cat "${f}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]]; then
    echo "[kill] pid ${pid} from ${f}"
    if is_windows; then
      taskkill //F //T //PID "${pid}" >/dev/null 2>&1 || true
    else
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
  fi
  rm -f "${f}"
}

stop_all() {
  echo "== stopping prior instances =="
  kill_pid_file "${BACKEND_PID_FILE}"
  kill_pid_file "${FRONTEND_PID_FILE}"
  kill_port "${BACKEND_PORT}"
  kill_port "${FRONTEND_PORT}"

  if is_windows; then
    # Kill every uvicorn + vite worker + multiprocessing spawn child.
    powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'uvicorn.*app\.main:create_app' -or \$_.CommandLine -match 'vite' -or \$_.CommandLine -match 'nohup.*uvicorn' -or \$_.CommandLine -match 'multiprocessing.spawn' -or \$_.CommandLine -match 'npm run dev' } | ForEach-Object { try { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }" >/dev/null 2>&1 || true
    # Also evict anything binding our ports (kernel-reported owner).
    powershell -NoProfile -Command "foreach (\$p in @(${BACKEND_PORT}, ${FRONTEND_PORT})) { \$c = Get-NetTCPConnection -LocalPort \$p -State Listen -ErrorAction SilentlyContinue; foreach (\$x in \$c) { try { Stop-Process -Id \$x.OwningProcess -Force -ErrorAction SilentlyContinue } catch {} } }" >/dev/null 2>&1 || true
  else
    pkill -f "uvicorn .*app.main:create_app" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    pkill -f "multiprocessing.spawn" 2>/dev/null || true
  fi

  echo "[docker] compose down (keep volumes)"
  docker compose down --remove-orphans >/dev/null 2>&1 || true
}

find_python() {
  if [[ -x "${ROOT_DIR}/.venv/Scripts/python.exe" ]]; then
    printf "%s" "${ROOT_DIR}/.venv/Scripts/python.exe"; return
  fi
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    printf "%s" "${ROOT_DIR}/.venv/bin/python"; return
  fi
  command -v python
}

wait_db_healthy() {
  local cid elapsed=0 timeout=120 status
  cid="$(docker compose ps -q db)"
  [[ -z "${cid}" ]] && { echo "no db container"; exit 1; }
  while (( elapsed < timeout )); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${cid}" 2>/dev/null || true)"
    [[ "${status}" == "healthy" || "${status}" == "running" ]] && { echo "[db] ${status}"; return 0; }
    [[ "${status}" == "unhealthy" || "${status}" == "exited" || "${status}" == "dead" ]] && { echo "[db] bad state: ${status}"; exit 1; }
    sleep 2; elapsed=$((elapsed+2))
  done
  echo "[db] timeout"; exit 1
}

start_db() {
  echo "== starting postgres (port ${DB_PORT}) =="
  docker compose up -d db
  wait_db_healthy
}

run_migrations() {
  echo "== alembic upgrade head =="
  local py; py="$(find_python)"
  # backend/.env mirrors root .env so pydantic-settings picks it up when alembic CWD=backend.
  cp -f "${ROOT_DIR}/.env" "${ROOT_DIR}/backend/.env" 2>/dev/null || true
  (
    cd "${ROOT_DIR}/backend"
    "${py}" -m alembic upgrade head \
      || { echo "[alembic] stamp head + retry"; "${py}" -m alembic stamp head && "${py}" -m alembic upgrade head; }
  )
}

start_backend() {
  echo "== starting backend ${BACKEND_HOST}:${BACKEND_PORT} =="
  local py; py="$(find_python)"
  (
    cd "${ROOT_DIR}"
    export PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:${PYTHONPATH}}"
    nohup "${py}" -m uvicorn app.main:create_app \
      --factory --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload \
      --reload-dir "${ROOT_DIR}/backend/app" \
      >"${BACKEND_LOG}" 2>&1 &
    echo $! > "${BACKEND_PID_FILE}"
  )
  echo "  pid=$(cat "${BACKEND_PID_FILE}")  log=${BACKEND_LOG}"
}

wait_backend_ready() {
  local elapsed=0 timeout=60
  while (( elapsed < timeout )); do
    if curl -fsS "http://${BACKEND_HOST}:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
      echo "[backend] ready"
      return 0
    fi
    sleep 2; elapsed=$((elapsed+2))
  done
  echo "[backend] not ready after ${timeout}s — see ${BACKEND_LOG}"
  return 1
}

start_frontend() {
  echo "== starting frontend ${FRONTEND_HOST}:${FRONTEND_PORT} =="
  if [[ ! -d "${ROOT_DIR}/frontend/node_modules" ]]; then
    ( cd "${ROOT_DIR}/frontend" && npm install )
  fi
  (
    cd "${ROOT_DIR}/frontend"
    nohup npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort \
      >"${FRONTEND_LOG}" 2>&1 &
    echo $! > "${FRONTEND_PID_FILE}"
  )
  echo "  pid=$(cat "${FRONTEND_PID_FILE}")  log=${FRONTEND_LOG}"
}

main() {
  stop_all
  start_db
  run_migrations
  start_backend
  wait_backend_ready || true
  start_frontend

  cat <<EOF

== stack up ==
  backend   http://${BACKEND_HOST}:${BACKEND_PORT}  (health: /api/health)
  frontend  http://${FRONTEND_HOST}:${FRONTEND_PORT}
  db        postgres://elfie:elfie@localhost:${DB_PORT}/elfie_labs

logs:   ${LOG_DIR}
stop:   bash scripts/dev_up.sh stop
tail:   tail -f ${BACKEND_LOG} ${FRONTEND_LOG}
EOF
}

case "${1:-up}" in
  up|start|"") main ;;
  stop|down)   stop_all ;;
  restart)     stop_all; main ;;
  logs)        tail -f "${BACKEND_LOG}" "${FRONTEND_LOG}" ;;
  *) echo "usage: $0 [up|stop|restart|logs]"; exit 1 ;;
esac
