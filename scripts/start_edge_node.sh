#!/usr/bin/env bash
set -euo pipefail

# Start exactly ONE edge-agent node.
# Use this script on each of 4 devices with different NODE_ID/PORT/PEERS.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${HOST:-0.0.0.0}"

# IMPORTANT: require explicit edge port in real deployment.
PORT="${PORT:-}"
if [[ -z "$PORT" ]]; then
  echo "ERROR: PORT is required (do not assume 29101). Example: PORT=9100 scripts/start_edge_node.sh" >&2
  exit 1
fi
PORT="${PORT:-29101}"

NODE_ID="${NODE_ID:-node-1}"
NODE_TYPE="${NODE_TYPE:-pi}"
PEERS="${PEERS:-}"

# Shared/core services (typically on desktop/server)
CORE_HOST="${CORE_HOST:-127.0.0.1}"
THRESHOLD_PORT="${THRESHOLD_PORT:-28000}"
DETECT_PORT="${DETECT_PORT:-28001}"
FINE_PORT="${FINE_PORT:-28002}"
COLLECTOR_PORT="${COLLECTOR_PORT:-29000}"

# SERVICE_MODE:
# - local: each node calls locally running microservices (default for decentralized deployment)
# - remote: edge calls services on CORE_HOST
SERVICE_MODE="${SERVICE_MODE:-local}"

DB_PATH="${DB_PATH:-./edge_agent_${NODE_ID}.db}"
CSV_DIR="${CSV_DIR:-}"
UPLOAD_EVERY="${UPLOAD_EVERY:-2}"

echo "[start] edge node: $NODE_ID ($NODE_TYPE)"
echo "[conf] host=$HOST port=$PORT peers=$PEERS"
echo "[conf] core=$CORE_HOST threshold=$THRESHOLD_PORT detect=$DETECT_PORT fine=$FINE_PORT collector=$COLLECTOR_PORT"

if [[ "$SERVICE_MODE" == "local" ]]; then
  EST_URL="http://127.0.0.1:8000/estimate"
  DET_URL="http://127.0.0.1:8001/detect/eval"
  FINE_URL="http://127.0.0.1:8002/fine/eval"
  COLLECTOR_URL="http://127.0.0.1:9000"
else
  EST_URL="http://$CORE_HOST:$THRESHOLD_PORT/ingest"
  DET_URL="http://$CORE_HOST:$DETECT_PORT/detect/eval"
  FINE_URL="http://$CORE_HOST:$FINE_PORT/fine/eval"
  COLLECTOR_URL="http://$CORE_HOST:$COLLECTOR_PORT"
fi

echo "[mode] SERVICE_MODE=$SERVICE_MODE"
echo "[paths] DB_PATH=$DB_PATH CSV_DIR=${CSV_DIR:-<auto>}"
echo "[urls] EST_URL=$EST_URL DET_URL=$DET_URL FINE_URL=$FINE_URL COLLECTOR_URL=$COLLECTOR_URL"

env \
  NODE_ID="$NODE_ID" \
  NODE_TYPE="$NODE_TYPE" \
  PEERS="$PEERS" \
  DET_URL="$DET_URL" \
  EST_URL="$EST_URL" \
  FINE_URL="$FINE_URL" \
  COLLECTOR_URL="$COLLECTOR_URL" \
  DB_PATH="$DB_PATH" \
  CSV_DIR="$CSV_DIR" \
  DET_URL="http://$CORE_HOST:$DETECT_PORT/detect/eval" \
  EST_URL="http://$CORE_HOST:$THRESHOLD_PORT/ingest" \
  FINE_URL="http://$CORE_HOST:$FINE_PORT/fine/eval" \
  COLLECTOR_URL="http://$CORE_HOST:$COLLECTOR_PORT" \
  DB_PATH="$DB_PATH" \
  UPLOAD_EVERY="$UPLOAD_EVERY" \
  "$PYTHON_BIN" -m uvicorn offload_system.edge_agent.app:app --host "$HOST" --port "$PORT"
