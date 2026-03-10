#!/usr/bin/env bash
set -euo pipefail

# Start shared/core services only (no edge agents):
# - threshold_service
# - svc_detect
# - suc_fine_detect
# - collector_pc

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${HOST:-0.0.0.0}"
THRESHOLD_PORT="${THRESHOLD_PORT:-28000}"
DETECT_PORT="${DETECT_PORT:-28001}"
FINE_PORT="${FINE_PORT:-28002}"
COLLECTOR_PORT="${COLLECTOR_PORT:-29000}"

PIDS=()

start_service() {
  local name="$1"
  shift
  echo "[start] $name"
  "$@" >"/tmp/${name}.log" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
}

cleanup() {
  echo "[cleanup] stopping ${#PIDS[@]} services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

wait_http_ok() {
  local url="$1"
  local retries="${2:-80}"
  for _ in $(seq 1 "$retries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

start_service threshold "$PYTHON_BIN" -m uvicorn threshold_service.app.main:app --host "$HOST" --port "$THRESHOLD_PORT"
start_service fine "$PYTHON_BIN" -m uvicorn suc_fine_detect.app.main:app --host "$HOST" --port "$FINE_PORT"
start_service detect env THRESHOLD_SERVICE_URL="http://127.0.0.1:$THRESHOLD_PORT" FINE_SERVICE_URL="http://127.0.0.1:$FINE_PORT" "$PYTHON_BIN" -m uvicorn svc_detect.app.main:app --host "$HOST" --port "$DETECT_PORT"
start_service collector "$PYTHON_BIN" -m uvicorn offload_system.collector_pc.app:app --host "$HOST" --port "$COLLECTOR_PORT"

wait_http_ok "http://127.0.0.1:$THRESHOLD_PORT/health"
wait_http_ok "http://127.0.0.1:$FINE_PORT/healthz"
wait_http_ok "http://127.0.0.1:$DETECT_PORT/healthz"
wait_http_ok "http://127.0.0.1:$COLLECTOR_PORT/health"

echo "[ok] core services ready"
echo "  threshold: http://<core-host>:$THRESHOLD_PORT"
echo "  detect:    http://<core-host>:$DETECT_PORT"
echo "  fine:      http://<core-host>:$FINE_PORT"
echo "  collector: http://<core-host>:$COLLECTOR_PORT"
echo

echo "[run] press Ctrl+C to stop core services"
while true; do sleep 1; done
