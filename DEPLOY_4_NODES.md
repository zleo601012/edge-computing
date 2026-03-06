# 4-Node Offload Deployment (Real Multi-Device Test)

This guide is for your **real target setup**: 4 edge devices running together and offloading tasks to each other.

## 1) Topology

- One desktop/server runs shared services:
  - threshold_service
  - svc_detect
  - suc_fine_detect
  - collector_pc
- Four edge devices run one `edge_agent` each.
- Each edge node has its own `NODE_ID` and `PEERS` set to other node addresses.

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

### pi1 (192.168.1.167)

```bash
CORE_HOST=192.168.1.169 PORT=${EDGE_PORT} NODE_ID=pi1 NODE_TYPE=pi \
PEERS="http://192.168.1.174:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi1.db scripts/start_edge_node.sh
```

### pi2 (192.168.1.174)

```bash
CORE_HOST=192.168.1.169 PORT=${EDGE_PORT} NODE_ID=pi2 NODE_TYPE=pi \
PEERS="http://192.168.1.167:${EDGE_PORT},http://192.168.1.175:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi2.db scripts/start_edge_node.sh
```

### pi3 (192.168.1.175)

```bash
CORE_HOST=192.168.1.169 PORT=${EDGE_PORT} NODE_ID=pi3 NODE_TYPE=pi \
PEERS="http://192.168.1.167:${EDGE_PORT},http://192.168.1.174:${EDGE_PORT},http://192.168.1.176:${EDGE_PORT}" \
DB_PATH=./edge_pi3.db scripts/start_edge_node.sh
```

### pi6 (192.168.1.176)

```bash
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
