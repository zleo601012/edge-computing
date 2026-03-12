#!/usr/bin/env bash
set -euo pipefail

# Start exactly ONE edge-agent node.
# Use this script on each device with different NODE_ID/PORT/PEERS.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${HOST:-0.0.0.0}"
SCRIPT_VERSION="2026-03-12-clean2"
SCRIPT_GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

PORT="${PORT:-}"
if [[ -z "$PORT" ]]; then
  echo "ERROR: PORT is required. Example: PORT=9100 scripts/start_edge_node.sh" >&2
  exit 1
fi

NODE_ID="${NODE_ID:-node-1}"
NODE_TYPE="${NODE_TYPE:-pi}"
PEERS="${PEERS:-}"

# Optional: auto-build PEERS from node ip list.
AUTO_PEERS="${AUTO_PEERS:-0}"
NODE_IP="${NODE_IP:-}"
CLUSTER_NODE_IPS="${CLUSTER_NODE_IPS:-}" # csv: ip1,ip2,ip3

# shared/core host mode
CORE_HOST="${CORE_HOST:-127.0.0.1}"
THRESHOLD_PORT="${THRESHOLD_PORT:-28000}"
DETECT_PORT="${DETECT_PORT:-28001}"
FINE_PORT="${FINE_PORT:-28002}"
COLLECTOR_PORT="${COLLECTOR_PORT:-29000}"

# local mode defaults
LOCAL_PROFILE="${LOCAL_PROFILE:-default}"
if [[ "$LOCAL_PROFILE" == "18000" ]]; then
  DEFAULT_EST_URL="http://127.0.0.1:18000/ingest"
  DEFAULT_DET_URL="http://127.0.0.1:18001/detect/eval"
  DEFAULT_FINE_URL="http://127.0.0.1:18002/fine/eval"
  DEFAULT_COLLECTOR_URL="http://127.0.0.1:19000"
else
  DEFAULT_EST_URL="http://127.0.0.1:8000/ingest"
  DEFAULT_DET_URL="http://127.0.0.1:8001/detect/eval"
  DEFAULT_FINE_URL="http://127.0.0.1:8002/fine/eval"
  DEFAULT_COLLECTOR_URL="http://127.0.0.1:9000"
fi

# explicit EST_URL/DET_URL/FINE_URL/COLLECTOR_URL take precedence.
LOCAL_EST_URL="${EST_URL:-${LOCAL_EST_URL:-$DEFAULT_EST_URL}}"
LOCAL_DET_URL="${DET_URL:-${LOCAL_DET_URL:-$DEFAULT_DET_URL}}"
LOCAL_FINE_URL="${FINE_URL:-${LOCAL_FINE_URL:-$DEFAULT_FINE_URL}}"
LOCAL_COLLECTOR_URL="${COLLECTOR_URL:-${LOCAL_COLLECTOR_URL:-$DEFAULT_COLLECTOR_URL}}"

AUTO_K3S_URLS="${AUTO_K3S_URLS:-0}"
K3S_NAMESPACE="${K3S_NAMESPACE:-default}"
K3S_MODE="${K3S_MODE:-nodeport}" # nodeport | clusterip
K3S_NODE_IP="${K3S_NODE_IP:-}"
K3S_EST_SVC="${K3S_EST_SVC:-threshold-service}"
K3S_DET_SVC="${K3S_DET_SVC:-svc-detect}"
K3S_FINE_SVC="${K3S_FINE_SVC:-suc-fine-detect}"

SERVICE_MODE="${SERVICE_MODE:-local}" # local | remote
DB_PATH="${DB_PATH:-./edge_agent_${NODE_ID}.db}"
CSV_DIR="${CSV_DIR:-}"
UPLOAD_EVERY="${UPLOAD_EVERY:-2}"
PRECHECK_URLS="${PRECHECK_URLS:-1}"

if [[ "$AUTO_PEERS" == "1" ]]; then
  if [[ -z "$NODE_IP" ]]; then
    NODE_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [[ -z "$NODE_IP" ]]; then
    echo "ERROR: AUTO_PEERS=1 requires NODE_IP (or hostname -I)." >&2
    exit 1
  fi
  if [[ -z "$CLUSTER_NODE_IPS" ]]; then
    echo "ERROR: AUTO_PEERS=1 requires CLUSTER_NODE_IPS (comma-separated IP list)." >&2
    exit 1
  fi

  AUTO_BUILT_PEERS=""
  IFS=',' read -r -a IPS <<< "$CLUSTER_NODE_IPS"
  for ip in "${IPS[@]}"; do
    ip="$(echo "$ip" | xargs)"
    [[ -z "$ip" || "$ip" == "$NODE_IP" ]] && continue
    if [[ -z "$AUTO_BUILT_PEERS" ]]; then
      AUTO_BUILT_PEERS="http://$ip:$PORT"
    else
      AUTO_BUILT_PEERS="$AUTO_BUILT_PEERS,http://$ip:$PORT"
    fi
  done
  PEERS="$AUTO_BUILT_PEERS"
fi

if [[ "$AUTO_K3S_URLS" == "1" && "$SERVICE_MODE" == "local" ]]; then
  if [[ "$K3S_MODE" == "nodeport" && -z "$K3S_NODE_IP" ]]; then
    K3S_NODE_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [[ "$K3S_MODE" == "nodeport" && -z "$K3S_NODE_IP" ]]; then
    echo "ERROR: AUTO_K3S_URLS=1 nodeport mode requires K3S_NODE_IP." >&2
    exit 1
  fi
  if [[ ! -x "$ROOT_DIR/scripts/k3s_print_edge_urls.sh" ]]; then
    echo "ERROR: missing helper script: $ROOT_DIR/scripts/k3s_print_edge_urls.sh" >&2
    exit 1
  fi

  echo "[k3s] resolving LOCAL_* URLs from services"
  eval "$(
    KUBECTL_BIN="${KUBECTL_BIN:-kubectl}" \
    NAMESPACE="$K3S_NAMESPACE" \
    MODE="$K3S_MODE" \
    NODE_IP="$K3S_NODE_IP" \
    EST_SVC="$K3S_EST_SVC" \
    DET_SVC="$K3S_DET_SVC" \
    FINE_SVC="$K3S_FINE_SVC" \
    "$ROOT_DIR/scripts/k3s_print_edge_urls.sh"
  )"
fi

if [[ "$SERVICE_MODE" == "local" ]]; then
  EST_URL="$LOCAL_EST_URL"
  DET_URL="$LOCAL_DET_URL"
  FINE_URL="$LOCAL_FINE_URL"
  COLLECTOR_URL="$LOCAL_COLLECTOR_URL"
else
  EST_URL="http://$CORE_HOST:$THRESHOLD_PORT/ingest"
  DET_URL="http://$CORE_HOST:$DETECT_PORT/detect/eval"
  FINE_URL="http://$CORE_HOST:$FINE_PORT/fine/eval"
  COLLECTOR_URL="http://$CORE_HOST:$COLLECTOR_PORT"
fi

check_url() {
  local name="$1"
  local url="$2"
  "$PYTHON_BIN" - "$name" "$url" <<'PY'
import socket
import sys
from urllib.parse import urlparse

name, url = sys.argv[1], sys.argv[2]
u = urlparse(url)
host = u.hostname
port = u.port or (443 if (u.scheme or '').lower() == 'https' else 80)
if not host:
    print(f"ERROR: {name} invalid url: {url}", file=sys.stderr)
    sys.exit(2)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(2.0)
try:
    sock.connect((host, int(port)))
except Exception as e:
    print(f"ERROR: {name} tcp unreachable: {host}:{port} ({e})", file=sys.stderr)
    sys.exit(1)
finally:
    sock.close()
PY
}

if [[ "$PRECHECK_URLS" != "0" ]]; then
  check_url estimate "$EST_URL"
  check_url detect "$DET_URL"
  check_url fine "$FINE_URL"
fi

echo "[start] edge node: $NODE_ID ($NODE_TYPE)"
echo "[script] start_edge_node.sh version=$SCRIPT_VERSION git=$SCRIPT_GIT_SHA"
echo "[conf] host=$HOST port=$PORT peers=$PEERS"
echo "[mode] SERVICE_MODE=$SERVICE_MODE"
echo "[paths] DB_PATH=$DB_PATH CSV_DIR=${CSV_DIR:-<auto>}"
echo "[urls] EST_URL=$EST_URL DET_URL=$DET_URL FINE_URL=$FINE_URL COLLECTOR_URL=$COLLECTOR_URL"
echo "[precheck] PRECHECK_URLS=$PRECHECK_URLS"

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
  UPLOAD_EVERY="$UPLOAD_EVERY" \
  "$PYTHON_BIN" -m uvicorn offload_system.edge_agent.app:app --host "$HOST" --port "$PORT"
