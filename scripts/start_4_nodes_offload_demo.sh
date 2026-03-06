#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${HOST:-127.0.0.1}"

THRESHOLD_PORT="${THRESHOLD_PORT:-28000}"
DETECT_PORT="${DETECT_PORT:-28001}"
FINE_PORT="${FINE_PORT:-28002}"
COLLECTOR_PORT="${COLLECTOR_PORT:-29000}"

EDGE1_PORT="${EDGE1_PORT:-29101}"
EDGE2_PORT="${EDGE2_PORT:-29102}"
EDGE3_PORT="${EDGE3_PORT:-29103}"
EDGE4_PORT="${EDGE4_PORT:-29104}"

MODE="${1:-run}"

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

EDGE1_URL="http://$HOST:$EDGE1_PORT"
EDGE2_URL="http://$HOST:$EDGE2_PORT"
EDGE3_URL="http://$HOST:$EDGE3_PORT"
EDGE4_URL="http://$HOST:$EDGE4_PORT"

rm -f /tmp/edge_node{1,2,3,4}.db /tmp/edge_node{1,2,3,4}.db-shm /tmp/edge_node{1,2,3,4}.db-wal

start_service threshold "$PYTHON_BIN" -m uvicorn threshold_service.app.main:app --host "$HOST" --port "$THRESHOLD_PORT"
start_service fine "$PYTHON_BIN" -m uvicorn suc_fine_detect.app.main:app --host "$HOST" --port "$FINE_PORT"
start_service detect env THRESHOLD_SERVICE_URL="http://$HOST:$THRESHOLD_PORT" FINE_SERVICE_URL="http://$HOST:$FINE_PORT" "$PYTHON_BIN" -m uvicorn svc_detect.app.main:app --host "$HOST" --port "$DETECT_PORT"
start_service collector "$PYTHON_BIN" -m uvicorn offload_system.collector_pc.app:app --host "$HOST" --port "$COLLECTOR_PORT"

# Ring peers: 1->2->3->4->1 (forces mutual offload path)
start_service edge1 env NODE_ID="node-1" NODE_TYPE="pi" PEERS="$EDGE2_URL" DET_URL="http://$HOST:$DETECT_PORT/detect/eval" EST_URL="http://$HOST:$THRESHOLD_PORT/ingest" FINE_URL="http://$HOST:$FINE_PORT/fine/eval" COLLECTOR_URL="http://$HOST:$COLLECTOR_PORT" DB_PATH="/tmp/edge_node1.db" UPLOAD_EVERY=2 "$PYTHON_BIN" -m uvicorn offload_system.edge_agent.app:app --host "$HOST" --port "$EDGE1_PORT"
start_service edge2 env NODE_ID="node-2" NODE_TYPE="pi" PEERS="$EDGE3_URL" DET_URL="http://$HOST:$DETECT_PORT/detect/eval" EST_URL="http://$HOST:$THRESHOLD_PORT/ingest" FINE_URL="http://$HOST:$FINE_PORT/fine/eval" COLLECTOR_URL="http://$HOST:$COLLECTOR_PORT" DB_PATH="/tmp/edge_node2.db" UPLOAD_EVERY=2 "$PYTHON_BIN" -m uvicorn offload_system.edge_agent.app:app --host "$HOST" --port "$EDGE2_PORT"
start_service edge3 env NODE_ID="node-3" NODE_TYPE="pi" PEERS="$EDGE4_URL" DET_URL="http://$HOST:$DETECT_PORT/detect/eval" EST_URL="http://$HOST:$THRESHOLD_PORT/ingest" FINE_URL="http://$HOST:$FINE_PORT/fine/eval" COLLECTOR_URL="http://$HOST:$COLLECTOR_PORT" DB_PATH="/tmp/edge_node3.db" UPLOAD_EVERY=2 "$PYTHON_BIN" -m uvicorn offload_system.edge_agent.app:app --host "$HOST" --port "$EDGE3_PORT"
start_service edge4 env NODE_ID="node-4" NODE_TYPE="pi" PEERS="$EDGE1_URL" DET_URL="http://$HOST:$DETECT_PORT/detect/eval" EST_URL="http://$HOST:$THRESHOLD_PORT/ingest" FINE_URL="http://$HOST:$FINE_PORT/fine/eval" COLLECTOR_URL="http://$HOST:$COLLECTOR_PORT" DB_PATH="/tmp/edge_node4.db" UPLOAD_EVERY=2 "$PYTHON_BIN" -m uvicorn offload_system.edge_agent.app:app --host "$HOST" --port "$EDGE4_PORT"

echo "[wait] health checks"
wait_http_ok "http://$HOST:$THRESHOLD_PORT/health"
wait_http_ok "http://$HOST:$FINE_PORT/healthz"
wait_http_ok "http://$HOST:$DETECT_PORT/healthz"
wait_http_ok "http://$HOST:$COLLECTOR_PORT/health"
wait_http_ok "$EDGE1_URL/health"
wait_http_ok "$EDGE2_URL/health"
wait_http_ok "$EDGE3_URL/health"
wait_http_ok "$EDGE4_URL/health"
echo "[ok] all services healthy"

demo_one_node() {
  local edge_url="$1"
  local node_name="$2"
  local offset="$3"

  for i in $(seq 0 9); do
    local et
    et=$(awk "BEGIN{printf \"%.1f\", $offset + $i*5 + 4.2}")
    post_json "$edge_url/ingest" "{\"trace_id\":\"warm-$node_name-$i\",\"event_time\":$et,\"payload\":{\"node_id\":\"$node_name\",\"ts\":$i,\"values\":{\"COD\":100,\"TN\":20,\"BOD\":40,\"Am\":5}}}" >/dev/null
    sleep 0.08
  done

  local et_bad
  et_bad=$(awk "BEGIN{printf \"%.1f\", $offset + 54.2}")
  post_json "$edge_url/ingest" "{\"trace_id\":\"abn-$node_name\",\"event_time\":$et_bad,\"payload\":{\"node_id\":\"$node_name\",\"ts\":11,\"values\":{\"COD\":500,\"TN\":20,\"BOD\":40,\"Am\":5}}}" >/dev/null
}

run_demo() {
  echo "[demo] warmup + abnormal events for all 4 nodes"
  demo_one_node "$EDGE1_URL" "ENT_1" 0
  demo_one_node "$EDGE2_URL" "ENT_2" 100
  demo_one_node "$EDGE3_URL" "ENT_3" 200
  demo_one_node "$EDGE4_URL" "ENT_4" 300

  sleep 3

  echo "[demo] offload summary"
  "$PYTHON_BIN" - <<'PY'
import sqlite3

def show(db, name):
    conn=sqlite3.connect(db)
    cur=conn.cursor()
    cur.execute("select count(*) from fine_result where offloaded=1 and ok=1")
    sent=cur.fetchone()[0]
    cur.execute("select count(*) from fine_result where origin!=executed_on")
    recv=cur.fetchone()[0]
    cur.execute("select slot,trace_id,offloaded,executed_on,origin,ok from fine_result order by id desc limit 3")
    rows=cur.fetchall()
    print(f"{name}: sent_offload_ok={sent}, received_or_executed_rows={recv}, latest={rows}")

for db,name in [('/tmp/edge_node1.db','node-1'),('/tmp/edge_node2.db','node-2'),('/tmp/edge_node3.db','node-3'),('/tmp/edge_node4.db','node-4')]:
    show(db,name)
PY
}

cat <<INFO

Services started:
- threshold: http://$HOST:$THRESHOLD_PORT
- detect:    http://$HOST:$DETECT_PORT
- fine:      http://$HOST:$FINE_PORT
- collector: http://$HOST:$COLLECTOR_PORT
- edge1:     $EDGE1_URL
- edge2:     $EDGE2_URL
- edge3:     $EDGE3_URL
- edge4:     $EDGE4_URL

Logs:
- /tmp/threshold.log /tmp/detect.log /tmp/fine.log /tmp/collector.log
- /tmp/edge1.log /tmp/edge2.log /tmp/edge3.log /tmp/edge4.log

Usage:
- Keep running: scripts/start_4_nodes_offload_demo.sh run
- Run demo then exit: scripts/start_4_nodes_offload_demo.sh demo
INFO

if [[ "$MODE" == "demo" ]]; then
  run_demo
  echo "[done] demo finished, exiting."
  exit 0
fi

echo "[run] press Ctrl+C to stop all services"
while true; do sleep 1; done
