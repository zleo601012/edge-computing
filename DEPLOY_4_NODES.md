# 4-Node Offload Deployment (Real Multi-Device Test)

This guide is for your **real target setup**: 4 edge devices running together and offloading tasks to each other.

## 1) Topology (decentralized, your setup)

- Four edge devices run one `edge_agent` each.
- Each device also runs its own local microservices (`8000/8001/8002`) and edge-agent calls local services directly.
- A laptop/desktop is only a **control terminal** (optional): used to trigger replay commands and check results.
- Each edge node has its own `NODE_ID` and `PEERS` set to other node addresses.

## 1.1 Service mode

For your setup, use `SERVICE_MODE=local`. In this mode edge-agent calls local services directly:
## 1) Topology

- One desktop/server runs shared services:
  - threshold_service
  - svc_detect
  - suc_fine_detect
  - collector_pc
- Four edge devices run one `edge_agent` each.
- Each edge node has its own `NODE_ID` and `PEERS` set to other node addresses.

## 1.1 Decentralized mode (your current setup)

If your cluster already runs the three microservices on each node locally (`8000/8001/8002`),
you should run edge-agent in `SERVICE_MODE=local` so it calls local services directly:

- estimate: `http://127.0.0.1:8000/estimate`
- detect: `http://127.0.0.1:8001/detect/eval`
- fine: `http://127.0.0.1:8002/fine/eval`

In this mode, `CORE_HOST` is not used for compute APIs.

If your local microservices are not on default ports, override startup vars:
- `LOCAL_EST_URL` (default `http://127.0.0.1:8000/estimate`)
- `LOCAL_DET_URL` (default `http://127.0.0.1:8001/detect/eval`)
- `LOCAL_FINE_URL` (default `http://127.0.0.1:8002/fine/eval`)

## 2) Start each edge node (on each device)
## 2) Start each edge node (on each device)
## 2) Start shared services (desktop/server)

From repo root:

```bash
scripts/start_core_services.sh
```

Keep this terminal running.

## 3) Start each edge node (on each device)

Assume (your real environment):
- core host IP: `192.168.1.169`
- node IPs:
  - pi7: `192.168.1.177`
  - pi2: `192.168.1.174`
  - pi3: `192.168.1.175`
  - pi4: `192.168.1.176`
  - pi1: `192.168.1.167`
  - pi2: `192.168.1.174`
  - pi3: `192.168.1.175`
  - pi6: `192.168.1.176`

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
DB_PATH=./edge_pi7.db scripts/start_edge_node.sh
### pi1 (192.168.1.167)

```bash
SERVICE_MODE=local PORT=${EDGE_PORT} NODE_ID=pi1 NODE_TYPE=pi \
CORE_HOST=192.168.1.169 PORT=${EDGE_PORT} NODE_ID=pi1 NODE_TYPE=pi \
PEERS="http://192.168.1.174:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi1.db scripts/start_edge_node.sh
```

### pi2 (192.168.1.174)

```bash
SERVICE_MODE=local PORT=${EDGE_PORT} NODE_ID=pi2 NODE_TYPE=pi \
PEERS="http://192.168.1.177:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi2.db CSV_DIR=./csv_pi2_live scripts/start_edge_node.sh
CORE_HOST=192.168.1.169 PORT=${EDGE_PORT} NODE_ID=pi2 NODE_TYPE=pi \
PEERS="http://192.168.1.167:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi2.db scripts/start_edge_node.sh
```

### pi3 (192.168.1.175)

```bash
SERVICE_MODE=local PORT=${EDGE_PORT} NODE_ID=pi3 NODE_TYPE=pi \
PEERS="http://192.168.1.177:${EDGE_PORT},http://192.168.1.174:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi3.db CSV_DIR=./csv_pi3_live scripts/start_edge_node.sh
DB_PATH=./edge_pi3.db scripts/start_edge_node.sh
```

### pi4 (192.168.1.176)

```bash
SERVICE_MODE=local PORT=${EDGE_PORT} NODE_ID=pi4 NODE_TYPE=pi \
PEERS="http://192.168.1.177:${EDGE_PORT},http://192.168.1.174:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT}" \
DB_PATH=./edge_pi4.db CSV_DIR=./csv_pi4_live scripts/start_edge_node.sh
```

## 3) Replay dataset to all 4 nodes (from your control machine, after all 4 nodes are up)
DB_PATH=./edge_pi4.db scripts/start_edge_node.sh
```

## 3) Replay dataset to all 4 nodes (from your control machine, after all 4 nodes are up)
## 4) Replay dataset to all 4 nodes (from desktop/server)

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
## 4.1 Auto replay with per-node datasets (recommended)

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


## 5) Troubleshooting: detect_result shows ConnectError

If CSV/DB shows many rows like `ConnectError('All connection attempts failed')`, edge-agent cannot reach local detect/fine/estimate URLs.

Check on each node:

```bash
curl -sS http://127.0.0.1:8000/estimate || true
curl -sS http://127.0.0.1:8001/detect/eval || true
curl -sS http://127.0.0.1:8002/fine/eval || true

# if all three fail, verify which ports are actually listening:
ss -lntp | grep -E ':8000|:8001|:8002|:28000|:28001|:28002' || true
docker ps --format 'table {{.Names}}	{{.Ports}}' || true
```


If your curl output is exactly:
- `Failed to connect to 127.0.0.1 port 8000`
- `Failed to connect to 127.0.0.1 port 8001`
- `Failed to connect to 127.0.0.1 port 8002`

then local microservices are not bound on those ports on that node. Point edge-agent to the real ports via `LOCAL_*_URL`, or start microservices on 8000/8001/8002.

If your local service ports/routes are different, start edge with explicit overrides:

```bash
SERVICE_MODE=local PORT=9100 NODE_ID=pi2 NODE_TYPE=pi \
PEERS="http://192.168.1.177:9100,http://192.168.1.175:9100,http://192.168.1.176:9100" \
DB_PATH=./edge_pi2.db CSV_DIR=./csv_pi2_live \
LOCAL_EST_URL=http://127.0.0.1:28000/ingest \
LOCAL_DET_URL=http://127.0.0.1:28001/detect/eval \
LOCAL_FINE_URL=http://127.0.0.1:28002/fine/eval \
bash scripts/start_edge_node.sh
```

`start_edge_node.sh` now performs fail-fast URL checks before launching uvicorn, so misconfigured URLs are reported immediately.



### 5.1 Quick connectivity test (new, exact commands)

After you start one edge node, immediately verify the *actual endpoints it uses* from the startup log line `[urls] ...`.

For your current k3s service IPs (as you provided), run on that same machine:

```bash
curl -sS -X POST http://10.43.197.158:8000/ingest -H 'content-type: application/json' -d '{}' | head
curl -sS -X POST http://10.43.3.242:8001/detect/eval -H 'content-type: application/json' -d '{}' | head
curl -sS -X POST http://10.43.196.176:8002/fine/eval -H 'content-type: application/json' -d '{}' | head
```

Expected: usually `422`/validation error JSON (this means service is reachable and route is correct).
If you get timeout/refused, host cannot reach ClusterIP directly; use NodePort URLs instead.

## 6) k3s deployment note (you said you use k3s)

When running edge-agent on host OS and microservices in k3s, `127.0.0.1:8000/8001/8002` usually does not work.
You must point edge-agent to k3s Service endpoints via `LOCAL_*_URL`.

Note: `offload_system/edge_agent/config.py` default URLs now point to k3s service DNS (`threshold-service`, `svc-detect`, `suc-fine-detect`).

### 6.1 Inspect service exposure

If you see `The connection to the server localhost:8080 was refused`, your kubeconfig is not loaded.
Use one of these first:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl -n default get svc -o wide

# or directly with k3s wrapper
k3s kubectl -n default get svc -o wide
```

If services are `ClusterIP`, use cluster IP URLs.
If services are `NodePort`, use node IP + nodePort URLs.

### 6.2 Auto-generate LOCAL_*_URL exports

```bash
# clusterIP mode (default)
KUBECONFIG=/etc/rancher/k3s/k3s.yaml NAMESPACE=default EST_SVC=threshold-service DET_SVC=svc-detect FINE_SVC=suc-fine-detect \
  scripts/k3s_print_edge_urls.sh

# nodePort mode
KUBECONFIG=/etc/rancher/k3s/k3s.yaml MODE=nodeport NODE_IP=192.168.1.174 NAMESPACE=default EST_SVC=threshold-service DET_SVC=svc-detect FINE_SVC=suc-fine-detect \
  scripts/k3s_print_edge_urls.sh
```

The script prints:
- `export LOCAL_EST_URL=...`
- `export LOCAL_DET_URL=...`
- `export LOCAL_FINE_URL=...`

Run those exports, then start edge-agent as usual.

The helper script will auto-fallback to `k3s kubectl` and auto-use `/etc/rancher/k3s/k3s.yaml` when available.


### 6.3 One-command startup for k3s nodes (recommended)

If all nodes hit the same connection error, enable automatic k3s URL resolution in startup:

```bash
SERVICE_MODE=local AUTO_K3S_URLS=1 K3S_MODE=nodeport K3S_NAMESPACE=default PORT=9100 NODE_ID=pi2 NODE_TYPE=pi PEERS="http://192.168.1.177:9100,http://192.168.1.175:9100,http://192.168.1.176:9100" DB_PATH=./edge_pi2.db CSV_DIR=./csv_pi2_live bash scripts/start_edge_node.sh
```

Notes:
- `AUTO_K3S_URLS=1` makes `start_edge_node.sh` call `scripts/k3s_print_edge_urls.sh` internally.
- For `K3S_MODE=nodeport`, it uses node IP automatically (`hostname -I` first IP).
- You can still explicitly set `K3S_NODE_IP=...` or `LOCAL_*_URL=...` if needed.


## 7) Do I need to change PEERS when testing?

- Single-node test: no peers needed (`PEERS=""` is fine).
- Multi-node test: peers must be the other edge node URLs.

To avoid manual peer editing on every node, use auto peer generation:

```bash
SERVICE_MODE=local AUTO_PEERS=1 CLUSTER_NODE_IPS="192.168.1.177,192.168.1.174,192.168.1.175,192.168.1.176" NODE_IP=192.168.1.174 PORT=9100 NODE_ID=pi2 NODE_TYPE=pi AUTO_K3S_URLS=1 K3S_MODE=nodeport K3S_NAMESPACE=default DB_PATH=./edge_pi2.db CSV_DIR=./csv_pi2_live bash scripts/start_edge_node.sh
```

This will auto-build:
- `PEERS=http://192.168.1.177:9100,http://192.168.1.175:9100,http://192.168.1.176:9100`

(automatically excludes current `NODE_IP`).


### 7.1 If LOCAL_*_URL seems ignored

Use a **single-line** command (avoid copy/paste line-break artifacts), for example:

```bash
SERVICE_MODE=local AUTO_K3S_URLS=0 AUTO_PEERS=1 CLUSTER_NODE_IPS="192.168.1.177,192.168.1.174,192.168.1.175,192.168.1.176" NODE_IP=192.168.1.177 PORT=9100 NODE_ID=pi7 NODE_TYPE=pi DB_PATH=./edge_pi7.db CSV_DIR=./csv_pi7_live LOCAL_EST_URL=http://127.0.0.1:18000/ingest LOCAL_DET_URL=http://127.0.0.1:18001/detect/eval LOCAL_FINE_URL=http://127.0.0.1:18002/fine/eval LOCAL_COLLECTOR_URL=http://127.0.0.1:19000 bash scripts/start_edge_node.sh
```

`start_edge_node.sh` accepts `EST_URL/DET_URL/FINE_URL/COLLECTOR_URL` and these explicitly override `LOCAL_*` values.
`start_edge_node.sh` also accepts `EST_URL/DET_URL/FINE_URL/COLLECTOR_URL` as compatibility aliases.



### 7.2 Short command for 18000/18001/18002 local services

If your local microservices run on 18000/18001/18002 (collector 19000), use this shortcut profile:

```bash
SERVICE_MODE=local LOCAL_PROFILE=18000 AUTO_K3S_URLS=0 AUTO_PEERS=1 CLUSTER_NODE_IPS="192.168.1.177,192.168.1.174,192.168.1.175,192.168.1.176" NODE_IP=192.168.1.177 PORT=9100 NODE_ID=pi7 NODE_TYPE=pi DB_PATH=./edge_pi7.db CSV_DIR=./csv_pi7_live bash scripts/start_edge_node.sh
```

This avoids typing `LOCAL_EST_URL/LOCAL_DET_URL/LOCAL_FINE_URL/LOCAL_COLLECTOR_URL` every time.
CORE_HOST=192.168.1.169 PORT=${EDGE_PORT} NODE_ID=pi3 NODE_TYPE=pi \
PEERS="http://192.168.1.167:${EDGE_PORT},http://192.168.1.174:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi3.db scripts/start_edge_node.sh
```

### pi6 (192.168.1.176)

```bash
SERVICE_MODE=local PORT=${EDGE_PORT} NODE_ID=pi6 NODE_TYPE=pi \
PEERS="http://192.168.1.167:${EDGE_PORT},http://192.168.1.174:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT}" \
DB_PATH=./edge_pi6.db scripts/start_edge_node.sh
CORE_HOST=192.168.1.169 PORT=${EDGE_PORT} NODE_ID=pi6 NODE_TYPE=pi \
PEERS="http://192.168.1.167:${EDGE_PORT},http://192.168.1.174:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT}" \
DB_PATH=./edge_pi6.db scripts/start_edge_node.sh
Assume:
- core host IP: `192.168.1.10`
- node IPs:
  - node-1: `192.168.1.21:29101`
  - node-2: `192.168.1.22:29101`
  - node-3: `192.168.1.23:29101`
  - node-4: `192.168.1.24:29101`

### node-1

```bash
CORE_HOST=192.168.1.10 PORT=29101 NODE_ID=node-1 NODE_TYPE=pi \
PEERS="http://192.168.1.22:29101,http://192.168.1.23:29101,http://192.168.1.24:29101" \
DB_PATH=./edge_node1.db scripts/start_edge_node.sh
```

### node-2

```bash
CORE_HOST=192.168.1.10 PORT=29101 NODE_ID=node-2 NODE_TYPE=pi \
PEERS="http://192.168.1.21:29101,http://192.168.1.23:29101,http://192.168.1.24:29101" \
DB_PATH=./edge_node2.db scripts/start_edge_node.sh
```

### node-3

```bash
CORE_HOST=192.168.1.10 PORT=29101 NODE_ID=node-3 NODE_TYPE=pi \
PEERS="http://192.168.1.21:29101,http://192.168.1.22:29101,http://192.168.1.24:29101" \
DB_PATH=./edge_node3.db scripts/start_edge_node.sh
```

### node-4

```bash
CORE_HOST=192.168.1.10 PORT=29101 NODE_ID=node-4 NODE_TYPE=pi \
PEERS="http://192.168.1.21:29101,http://192.168.1.22:29101,http://192.168.1.23:29101" \
DB_PATH=./edge_node4.db scripts/start_edge_node.sh
```

## 4) Replay dataset to all 4 nodes (from desktop/server)

Use existing replayer script and explicit node->agent mapping:

```bash
python3 -m offload_system.replayer.replay \
  --dataset dataset/node_1.csv \
  --agent-map-json '{"ENT_1":"http://192.168.1.167:${EDGE_PORT}","ENT_2":"http://192.168.1.174:${EDGE_PORT}","ENT_3":"http://192.168.1.175:${EDGE_PORT}","ENT_4":"http://192.168.1.176:${EDGE_PORT}"}' \
  --default-agent http://192.168.1.167:${EDGE_PORT} \
  --agent-map-json '{"ENT_1":"http://192.168.1.21:29101","ENT_2":"http://192.168.1.22:29101","ENT_3":"http://192.168.1.23:29101","ENT_4":"http://192.168.1.24:29101"}' \
  --default-agent http://192.168.1.21:29101 \
  --time-col ts \
  --node-col node_id \
  --relative-time \
  --slot-seconds 5 \
  --speed 10
```

## 5) Verify offloading happened

On each node check local DB has offload rows:

```bash
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('edge_pi7.db')
conn = sqlite3.connect('edge_pi1.db')
conn = sqlite3.connect('edge_node1.db')
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

### Export results to CSV (easier than opening DB directly)

If DB files are inconvenient to inspect, export per-table CSV files:

```bash
# example for pi7 db
scripts/export_edge_db_csv.sh ./edge_pi7.db ./csv_pi7
# outputs: csv_pi7/baseline.csv csv_pi7/detect_result.csv csv_pi7/fine_result.csv
```

You can run the same command on each node with its own DB path.

