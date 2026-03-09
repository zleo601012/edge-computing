#!/usr/bin/env bash
set -euo pipefail

# Run multiple dataset replayers in parallel, one dataset -> one edge node.
# This is for decentralized cluster testing where each node should consume its own health dataset.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
SPEED="${SPEED:-10}"
SLOT_SECONDS="${SLOT_SECONDS:-5}"
CONCURRENCY="${CONCURRENCY:-8}"

# Node URLs (edit/export for your environment)
PI7_URL="${PI7_URL:-http://192.168.1.177:9100}"
PI2_URL="${PI2_URL:-http://192.168.1.174:9100}"
PI3_URL="${PI3_URL:-http://192.168.1.175:9100}"
PI4_URL="${PI4_URL:-http://192.168.1.176:9100}"

# Dataset paths (edit/export for your environment)
PI7_DATASET="${PI7_DATASET:-dataset/node_1.csv}"
PI2_DATASET="${PI2_DATASET:-dataset/node_2.csv}"
PI3_DATASET="${PI3_DATASET:-dataset/node_3.csv}"
PI4_DATASET="${PI4_DATASET:-dataset/node_4.csv}"

run_one() {
  local name="$1"
  local dataset="$2"
  local url="$3"

  echo "[replay:$name] dataset=$dataset -> $url"
  "$PYTHON_BIN" -m offload_system.replayer.replay \
    --dataset "$dataset" \
    --default-agent "$url" \
    --time-col ts \
    --node-col node_id \
    --relative-time \
    --slot-seconds "$SLOT_SECONDS" \
    --speed "$SPEED" \
    --concurrency "$CONCURRENCY" \
    >"/tmp/replay_${name}.log" 2>&1

  echo "[replay:$name] done"
}

# Basic checks
for f in "$PI7_DATASET" "$PI2_DATASET" "$PI3_DATASET" "$PI4_DATASET"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: dataset not found: $f" >&2
    exit 1
  fi
done

echo "[start] parallel replay jobs"
run_one pi7 "$PI7_DATASET" "$PI7_URL" & P1=$!
run_one pi2 "$PI2_DATASET" "$PI2_URL" & P2=$!
run_one pi3 "$PI3_DATASET" "$PI3_URL" & P3=$!
run_one pi4 "$PI4_DATASET" "$PI4_URL" & P4=$!

wait "$P1" "$P2" "$P3" "$P4"

echo "[done] all replay jobs finished"
echo "logs: /tmp/replay_pi7.log /tmp/replay_pi2.log /tmp/replay_pi3.log /tmp/replay_pi4.log"
