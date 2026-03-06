# Full Functionality Smoke Test Report

This report records an end-to-end smoke test of all major runnable modules in this repository.

## Scope covered

- `main_node.py` standalone simulation loop
- `threshold_service` API (`/health`, `/ingest`, `/thresholds/{node_id}`)
- `svc_detect` API (`/healthz`, `/detect/eval`) and integration with threshold/fine services
- `suc_fine_detect` API (`/healthz`, `/fine/eval`)
- `offload_system/collector_pc` API (`/health`, `/upload_batch`)
- `offload_system/edge_agent` API (`/health`, `/ingest`, `/execute`)

## Commands executed

1. Start all services in one shell and run API checks:

```bash
python3 -m uvicorn threshold_service.app.main:app --host 127.0.0.1 --port 18000
python3 -m uvicorn suc_fine_detect.app.main:app --host 127.0.0.1 --port 18002
THRESHOLD_SERVICE_URL=http://127.0.0.1:18000 FINE_SERVICE_URL=http://127.0.0.1:18002 python3 -m uvicorn svc_detect.app.main:app --host 127.0.0.1 --port 18001
python3 -m uvicorn offload_system.collector_pc.app:app --host 127.0.0.1 --port 19000
NODE_ID=node-a DET_URL=http://127.0.0.1:18001/detect/eval EST_URL=http://127.0.0.1:18000/ingest FINE_URL=http://127.0.0.1:18002/fine/eval COLLECTOR_URL=http://127.0.0.1:19000 DB_PATH=/tmp/edge_a.db python3 -m uvicorn offload_system.edge_agent.app:app --host 127.0.0.1 --port 19100
```

2. Health checks:

```bash
curl -sSf http://127.0.0.1:18000/health
curl -sSf http://127.0.0.1:18002/healthz
curl -sSf http://127.0.0.1:18001/healthz
curl -sSf http://127.0.0.1:19000/health
curl -sSf http://127.0.0.1:19100/health
```

3. Threshold + detect + fine + collector + edge calls:

```bash
curl -sS -X POST http://127.0.0.1:18000/ingest -H 'content-type: application/json' -d '{"node_id":"ENT_1","ts":1,"values":{"COD":100,"TN":20,"BOD":40,"Am":5}}'
curl -sS http://127.0.0.1:18000/thresholds/ENT_1
curl -sS -X POST http://127.0.0.1:18002/fine/eval -H 'content-type: application/json' -d '{"event_id":"e1","slot_id":"1","node_type":"pi","ts":1,"values":{"COD":900,"TN":80,"BOD":500,"Am":30},"exceed_ratio":0.8}'
curl -sS -X POST http://127.0.0.1:18001/detect/eval -H 'content-type: application/json' -d '{"slot_id":"1","node_id":"ENT_1","ts":1,"values":{"COD":900,"TN":80,"BOD":500,"Am":30}}'
curl -sS -X POST http://127.0.0.1:19000/upload_batch -H 'content-type: application/json' -d '{"batch_id":"b1","sent_ts":1,"node_id":"ENT_1","node_type":"pi","slots":[1],"baseline":[{"slot":1,"trace_id":"t1","created_ts":1,"payload":{"a":1}}],"detect":[{"slot":1,"trace_id":"t1","created_ts":1,"abnormal":1,"payload":{"b":2}}],"fine":[{"slot":1,"trace_id":"t1","created_ts":1,"offloaded":0,"executed_on":"ENT_1","origin":"ENT_1","ok":1,"duration_ms":12.3,"payload":{"c":3}}]}'
curl -sS -X POST http://127.0.0.1:19100/ingest -H 'content-type: application/json' -d '{"trace_id":"x1","event_time":4,"payload":{"node_id":"ENT_1","ts":1,"values":{"COD":100}}}'
curl -sS -X POST http://127.0.0.1:19100/execute -H 'content-type: application/json' -d '{"stage":"fine","slot":1,"payload":{"event_id":"e2","slot_id":"1","node_type":"pi","ts":1,"values":{"COD":600},"exceed_ratio":0.4},"trace_id":"x2","origin":"ENT_1"}'
```

4. Validate detect→fine true-positive path after minimum threshold samples:

```bash
for i in $(seq 1 10); do
  curl -sS -X POST http://127.0.0.1:18100/ingest -H 'content-type: application/json' -d "{\"node_id\":\"ENT_9\",\"ts\":$i,\"values\":{\"COD\":100,\"TN\":20,\"BOD\":40,\"Am\":5}}" >/dev/null
done
curl -sS -X POST http://127.0.0.1:18101/detect/eval -H 'content-type: application/json' -d '{"slot_id":"11","node_id":"ENT_9","ts":11,"values":{"COD":500,"TN":20,"BOD":40,"Am":5}}'
```

5. Standalone node loop smoke test:

```bash
head -n 2 dataset/node_1.csv > /tmp/node1_one_row.csv
python3 main_node.py --node-id 1 --csv /tmp/node1_one_row.csv --out /tmp/results_node1.csv
cat /tmp/results_node1.csv
```

## Results summary

- ✅ All five services start and health endpoints respond.
- ✅ `threshold_service` ingest/query works.
- ✅ `svc_detect` works with threshold service and can trigger fine-stage enrichment after thresholds are warm (>= 10 samples).
- ✅ `suc_fine_detect` works when request schema is correct (`exceed_ratio` must be an object/dict, not float).
- ✅ `collector_pc` batch upload endpoint works.
- ✅ `edge_agent` health + ingest work.
- ⚠️ `edge_agent` `/execute` against `suc_fine_detect /fine/eval` fails with HTTP 422 under current direct wiring, because `edge_agent` sends `{slot, trace_id, payload}` style payload while fine service expects `FineRequest` fields at top-level (`event_id`, `node_type`, `values`, `exceed_ratio` dict, ...).

## Conclusion

- The repository is **mostly runnable at service level** and core components can be started and exercised.
- A **schema adapter mismatch** remains between `offload_system.edge_agent` fine-call contract and `suc_fine_detect` fine API contract for a true end-to-end offload fine-execution success path.
