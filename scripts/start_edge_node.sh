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

# Optional: auto-build PEERS from cluster node IP list (testing convenience).
AUTO_PEERS="${AUTO_PEERS:-0}"
NODE_IP="${NODE_IP:-}"
CLUSTER_NODE_IPS="${CLUSTER_NODE_IPS:-}"   # e.g. "192.168.1.177,192.168.1.174,192.168.1.175,192.168.1.176"

# Shared/core services (typically on desktop/server)
CORE_HOST="${CORE_HOST:-127.0.0.1}"
THRESHOLD_PORT="${THRESHOLD_PORT:-28000}"
DETECT_PORT="${DETECT_PORT:-28001}"
FINE_PORT="${FINE_PORT:-28002}"
COLLECTOR_PORT="${COLLECTOR_PORT:-29000}"

# Optional per-node local microservice URLs (used when SERVICE_MODE=local).
LOCAL_PROFILE="${LOCAL_PROFILE:-default}"
if [[ "$LOCAL_PROFILE" == "18000" ]]; then
  _DEFAULT_EST_URL="http://127.0.0.1:18000/ingest"
  _DEFAULT_DET_URL="http://127.0.0.1:18001/detect/eval"
  _DEFAULT_FINE_URL="http://127.0.0.1:18002/fine/eval"
  _DEFAULT_COLLECTOR_URL="http://127.0.0.1:19000"
else
  # 修正：将默认路径由 /estimate 改为 /ingest
  _DEFAULT_EST_URL="http://127.0.0.1:8000/ingest"
  _DEFAULT_DET_URL="http://127.0.0.1:8001/detect/eval"
  _DEFAULT_FINE_URL="http://127.0.0.1:8002/fine/eval"
  _DEFAULT_COLLECTOR_URL="http://127.0.0.1:9000"
fi

# 优先级：环境变量 > 默认值
LOCAL_EST_URL="${LOCAL_EST_URL:-${EST_URL:-${_DEFAULT_EST_URL}}}"
LOCAL_DET_URL="${LOCAL_DET_URL:-${DET_URL:-${_DEFAULT_DET_URL}}}"
LOCAL_FINE_URL="${LOCAL_FINE_URL:-${FINE_URL:-${_DEFAULT_FINE_URL}}}"
LOCAL_COLLECTOR_URL="${LOCAL_COLLECTOR_URL:-${COLLECTOR_URL:-${_DEFAULT_COLLECTOR_URL}}}"

# Optional: auto-resolve LOCAL_*_URL from k3s services
AUTO_K3S_URLS="${AUTO_K3S_URLS:-0}"
K3S_NAMESPACE="${K3S_NAMESPACE:-default}"
K3S_MODE="${K3S_MODE:-nodeport}"
K3S_NODE_IP="${K3S_NODE_IP:-}"
K3S_EST_SVC="${K3S_EST_SVC:-threshold-service}"
K3S_DET_SVC="${K3S_DET_SVC:-svc-detect}"
K3S_FINE_SVC="${K3S_FINE_SVC:-suc-fine-detect}"

SERVICE_MODE="${SERVICE_MODE:-local}"

DB_PATH="${DB_PATH:-./edge_agent_${NODE_ID}.db}"
CSV_DIR="${CSV_DIR:-}"
UPLOAD_EVERY="${UPLOAD_EVERY:-2}"
PRECHECK_URLS="${PRECHECK_URLS:-1}"

echo "[start] edge node: $NODE_ID ($NODE_TYPE)"

if [[ "$AUTO_PEERS" == "1" ]]; then
  if [[ -z "$NODE_IP" ]]; then
    NODE_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [[ -z "$CLUSTER_NODE_IPS" ]]; then
    echo "ERROR: AUTO_PEERS=1 requires CLUSTER_NODE_IPS." >&2
    exit 1
  fi
  AUTO_BUILT_PEERS=""
  IFS=',' read -r -a _ips <<< "$CLUSTER_NODE_IPS"
  for _ip in "${_ips[@]}"; do
    _ip="$(echo "$_ip" | xargs)"
    [[ -z "$_ip" || "$_ip" == "$NODE_IP" ]] && continue
    if [[ -z "$AUTO_BUILT_PEERS" ]]; then
      AUTO_BUILT_PEERS="http://$_ip:$PORT"
    else
      AUTO_BUILT_PEERS="${AUTO_BUILT_PEERS},http://$_ip:$PORT"
    fi
  done
  PEERS="$AUTO_BUILT_PEERS"
fi

if [[ "$AUTO_K3S_URLS" == "1" && "$SERVICE_MODE" == "local" ]]; then
  echo "[k3s] resolving LOCAL_*_URL from services..."
  eval "$(KUBECTL_BIN=\"${KUBECTL_BIN:-kubectl}\" NAMESPACE=\"$K3S_NAMESPACE\" MODE=\"$K3S_MODE\" NODE_IP=\"$K3S_NODE_IP\" EST_SVC=\"$K3S_EST_SVC\" DET_SVC=\"$K3S_DET_SVC\" FINE_SVC=\"$K3S_FINE_SVC\" \"$ROOT_DIR/scripts/k3s_print_edge_urls.sh\")"
fi

# 关键修正：移除此处对 EST_URL/DET_URL 等的二次硬编码覆盖
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

echo "[urls] EST_URL=$EST_URL DET_URL=$DET_URL FINE_URL=$FINE_URL"

check_url() {
  local name="$1"
  local url="$2"
  "$PYTHON_BIN" - "$name" "$url" <<'PY'
import socket
import sys
from urllib.parse import urlparse
name, url = sys.argv[1], sys.argv[2]
u = urlparse(url)
host, port = u.hostname, u.port or (443 if u.scheme == 'https' else 80)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(2.0)
try:
    sock.connect((host, int(port)))
except Exception as e:
    print(f"ERROR: {name} unreachable: {host}:{port} ({e})", file=sys.stderr)
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

# 关键修正：在 env 中仅保留动态变量，删除末尾重复的 CORE_HOST 覆盖行
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
