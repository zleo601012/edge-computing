# 4-Node Offload Deployment (Real Multi-Device Test)

This guide is for your **real target setup**: 4 edge devices running together and offloading tasks to each other.

## 1) Topology (decentralized, your setup)

- Four edge devices run one `edge_agent` each.
- Each device also runs its own local microservices (`8000/8001/8002`) and edge-agent calls local services directly.
- A laptop/desktop is only a **control terminal** (optional): used to trigger replay commands and check results.
- Each edge node has its own `NODE_ID` and `PEERS` set to other node addresses.

## 1.1 Service mode

For your setup, use `SERVICE_MODE=local`. In this mode edge-agent calls local services directly:

- estimate: `http://127.0.0.1:8000/estimate`
- detect: `http://127.0.0.1:8001/detect/eval`
- fine: `http://127.0.0.1:8002/fine/eval`

In this mode, `CORE_HOST` is not used for compute APIs.

## 2) Start each edge node (on each device)

Assume (your real environment):
- core host IP: `192.168.1.169`
- node IPs:
  - pi7: `192.168.1.177`
  - pi2: `192.168.1.174`
  - pi3: `192.168.1.175`
  - pi4: `192.168.1.176`

> Important: do **not** assume edge port is `29101`.
> First find each node's actual edge port (if already running):

```bash
ps -ef | grep -E 'uvicorn|offload_system.edge_agent.app:app' | grep -v grep
ss -lntp | grep -E 'LISTEN|python|uvicorn'
```

Let the discovered edge port be `EDGE_PORT`. Use the same value in startup and `PEERS`.


### Recommended startup order (important)

1. On each Pi, start `edge_agent` first (`SERVICE_MODE=local PORT=9100 ...`).
2. Confirm each node is healthy:

```bash
curl -sS http://192.168.1.177:9100/health
curl -sS http://192.168.1.174:9100/health
curl -sS http://192.168.1.175:9100/health
curl -sS http://192.168.1.176:9100/health
```

3. Then run replay from laptop/desktop (or any machine that can access all 4 node IPs).

If you run replay before nodes are started, there will be no compute results.

### pi7 (192.168.1.177)

```bash
SERVICE_MODE=local PORT=${EDGE_PORT} NODE_ID=pi7 NODE_TYPE=pi \
PEERS="http://192.168.1.174:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi7.db CSV_DIR=./csv_pi7_live scripts/start_edge_node.sh
```

### pi2 (192.168.1.174)

```bash
SERVICE_MODE=local PORT=${EDGE_PORT} NODE_ID=pi2 NODE_TYPE=pi \
PEERS="http://192.168.1.177:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi2.db CSV_DIR=./csv_pi2_live scripts/start_edge_node.sh
```

### pi3 (192.168.1.175)

```bash
SERVICE_MODE=local PORT=${EDGE_PORT} NODE_ID=pi3 NODE_TYPE=pi \
PEERS="http://192.168.1.177:${EDGE_PORT},http://192.168.1.174:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi3.db CSV_DIR=./csv_pi3_live scripts/start_edge_node.sh
```

### pi4 (192.168.1.176)

```bash
SERVICE_MODE=local PORT=${EDGE_PORT} NODE_ID=pi4 NODE_TYPE=pi \
PEERS="http://192.168.1.177:${EDGE_PORT},http://192.168.1.174:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT}" \
DB_PATH=./edge_pi4.db CSV_DIR=./csv_pi4_live scripts/start_edge_node.sh
```

## 3) Replay dataset to all 4 nodes (from your control machine, after all 4 nodes are up)

Use existing replayer script and explicit node->agent mapping:

```bash
python3 -m offload_system.replayer.replay \
  --dataset dataset/node_1.csv \
  --agent-map-json '{"ENT_1":"http://192.168.1.177:${EDGE_PORT}","ENT_2":"http://192.168.1.174:${EDGE_PORT}","ENT_3":"http://192.168.1.175:${EDGE_PORT}","ENT_4":"http://192.168.1.176:${EDGE_PORT}"}' \
  --default-agent http://192.168.1.177:${EDGE_PORT} \
  --time-col ts \
  --node-col node_id \
  --relative-time \
  --slot-seconds 5 \
  --speed 10
```


## 3.1 Auto replay with per-node datasets (recommended)

If you need each node to consume its own health dataset automatically (no manual row-by-row feeding), use:

```bash
scripts/run_multi_dataset_replay.sh
```

Default mapping in this script:
- `pi7` <- `dataset/node_1.csv`
- `pi2` <- `dataset/node_2.csv`
- `pi3` <- `dataset/node_3.csv`
- `pi4` <- `dataset/node_4.csv`

You can override via env vars, for example:

```bash
SPEED=20 SLOT_SECONDS=5 PI7_URL=http://192.168.1.177:9100 PI7_DATASET=dataset/node_1.csv PI2_URL=http://192.168.1.174:9100 PI2_DATASET=dataset/node_2.csv PI3_URL=http://192.168.1.175:9100 PI3_DATASET=dataset/node_3.csv PI4_URL=http://192.168.1.176:9100 PI4_DATASET=dataset/node_4.csv scripts/run_multi_dataset_replay.sh
```

## 4) Verify offloading happened

On each node check local DB has offload rows:

```bash
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('edge_pi7.db')
cur = conn.cursor()
cur.execute('select count(*) from fine_result where offloaded=1')
print('offloaded rows:', cur.fetchone()[0])
cur.execute('select count(*) from fine_result where origin!=executed_on')
print('remote execution rows:', cur.fetchone()[0])
PY
```

If both are >0 across nodes, cross-node offloading is working.

Note: edge-agent now writes CSV continuously during runtime.
- Default CSV dir: `${DB_PATH without .db}_csv`
- Files: `baseline.csv`, `detect_result.csv`, `fine_result.csv`
- You can override with `CSV_DIR=...` in `scripts/start_edge_node.sh` startup env.
