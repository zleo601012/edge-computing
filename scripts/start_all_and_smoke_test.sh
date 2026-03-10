#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-127.0.0.1}"
THRESHOLD_PORT="${THRESHOLD_PORT:-18000}"
DETECT_PORT="${DETECT_PORT:-18001}"
FINE_PORT="${FINE_PORT:-18002}"
COLLECTOR_PORT="${COLLECTOR_PORT:-19000}"
EDGE_PORT="${EDGE_PORT:-19100}"

NODE_ID="${NODE_ID:-node-a}"
NODE_TYPE="${NODE_TYPE:-pi}"
UPLOAD_EVERY="${UPLOAD_EVERY:-2}"
EDGE_DB_PATH="${EDGE_DB_PATH:-/tmp/edge_agent_smoke.db}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

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

post_json() {
  local url="$1"
  local body="$2"
  curl -fsS -X POST "$url" -H 'content-type: application/json' -d "$body"
}

rm -f "$EDGE_DB_PATH" "$EDGE_DB_PATH-shm" "$EDGE_DB_PATH-wal"

start_service threshold "$PYTHON_BIN" -m uvicorn threshold_service.app.main:app --host "$HOST" --port "$THRESHOLD_PORT"
start_service fine "$PYTHON_BIN" -m uvicorn suc_fine_detect.app.main:app --host "$HOST" --port "$FINE_PORT"
start_service detect env THRESHOLD_SERVICE_URL="http://$HOST:$THRESHOLD_PORT" FINE_SERVICE_URL="http://$HOST:$FINE_PORT" "$PYTHON_BIN" -m uvicorn svc_detect.app.main:app --host "$HOST" --port "$DETECT_PORT"
start_service collector "$PYTHON_BIN" -m uvicorn offload_system.collector_pc.app:app --host "$HOST" --port "$COLLECTOR_PORT"
start_service edge env NODE_ID="$NODE_ID" NODE_TYPE="$NODE_TYPE" DET_URL="http://$HOST:$DETECT_PORT/detect/eval" EST_URL="http://$HOST:$THRESHOLD_PORT/ingest" FINE_URL="http://$HOST:$FINE_PORT/fine/eval" COLLECTOR_URL="http://$HOST:$COLLECTOR_PORT" DB_PATH="$EDGE_DB_PATH" UPLOAD_EVERY="$UPLOAD_EVERY" "$PYTHON_BIN" -m uvicorn offload_system.edge_agent.app:app --host "$HOST" --port "$EDGE_PORT"

echo "[wait] health checks..."
wait_http_ok "http://$HOST:$THRESHOLD_PORT/health"
wait_http_ok "http://$HOST:$FINE_PORT/healthz"
wait_http_ok "http://$HOST:$DETECT_PORT/healthz"
wait_http_ok "http://$HOST:$COLLECTOR_PORT/health"
wait_http_ok "http://$HOST:$EDGE_PORT/health"

echo "[ok] all services healthy"

echo "[warmup] feeding edge ingest events for threshold warmup"
for i in $(seq 0 9); do
  et=$(awk "BEGIN{printf \"%.1f\", $i*5+4.2}")
  post_json "http://$HOST:$EDGE_PORT/ingest" "{\"trace_id\":\"warm-$i\",\"event_time\":$et,\"payload\":{\"node_id\":\"ENT_9\",\"ts\":$i,\"values\":{\"COD\":100,\"TN\":20,\"BOD\":40,\"Am\":5}}}" >/dev/null
  sleep 0.12
done

echo "[test] edge /execute -> fine service"
EXEC_RESP="$(post_json "http://$HOST:$EDGE_PORT/execute" '{"stage":"fine","slot":77,"payload":{"event_id":"manual-e","slot_id":"77","node_type":"pi","ts":1,"values":{"COD":600},"exceed_ratio":{"COD":2.0}},"trace_id":"manual-t","origin":"ENT_9"}')"
echo "$EXEC_RESP"

echo "[verify] checking execute response contains \"ok\": true"
echo "$EXEC_RESP" | "$PYTHON_BIN" -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ok") is True, d; print("execute_ok=true")'

echo "[done] smoke test passed"
echo "Logs: /tmp/threshold.log /tmp/fine.log /tmp/detect.log /tmp/collector.log /tmp/edge.log"
