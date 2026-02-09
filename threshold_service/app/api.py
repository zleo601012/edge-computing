from typing import List, Dict
from fastapi import APIRouter, Body
from .models import Observation, IngestResponse, BatchIngestResponse
from .profiles import PROFILES, DEFAULT_PROFILE
from .state import infer_node_type
from .estimator import EstimatorManager
from .storage import ThresholdStore
store = ThresholdStore(db_path="thresholds.db")

router = APIRouter()
mgr = EstimatorManager(PROFILES, DEFAULT_PROFILE)

@router.post("/ingest", response_model=IngestResponse)
def ingest(obs: Observation):
    est = mgr.get_or_create(obs.node_id)
    thr = est.ingest_one(obs.values)
    # ✅ 写入SQLite（只保存最新一条）
    slot_id = int(obs.ts) if obs.ts is not None and str(obs.ts).isdigit() else est.counter
    store.upsert_latest(obs.node_id, slot_id, thr)
    return IngestResponse(
        node_id=obs.node_id,
        node_type=infer_node_type(obs.node_id),
        counter=est.counter,
        thresholds=thr
    )

@router.post("/ingest_batch", response_model=BatchIngestResponse)
def ingest_batch(observations: List[Observation] = Body(...)):
    counts: Dict[str, int] = {}
    for obs in observations:
        est = mgr.get_or_create(obs.node_id)
        est.ingest_one(obs.values)
        counts[obs.node_id] = est.counter
    return BatchIngestResponse(ingested=len(observations), nodes=counts)

@router.get("/thresholds/{node_id}")
def get_thresholds(node_id: str):
    est = mgr.get_or_create(node_id)
    return {
        "node_id": node_id,
        "node_type": infer_node_type(node_id),
        "counter": est.counter,
        "thresholds": est.thr,
        "long_thresholds": est.long_thr,
        "buffer_sizes": {m: {"short": len(est.short_buf[m]), "long": len(est.long_buf[m])} for m in est.short_buf}
    }

@router.get("/nodes")
def list_nodes():
    return [{"node_id": nid, "node_type": infer_node_type(nid), "counter": est.counter} for nid, est in mgr.nodes.items()]
