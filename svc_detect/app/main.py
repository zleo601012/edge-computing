import os
import uuid, time
from fastapi import FastAPI, HTTPException
import httpx
from .models import DetectRequest, DetectResponse
from .db import ensure_events_table, load_thresholds, save_event
from .rules import compute_exceed, decide_level, fine_detect_stub

app = FastAPI(title="svc-detect", version="1.0.0")
THRESHOLD_SERVICE_URL = os.getenv("THRESHOLD_SERVICE_URL", "http://127.0.0.1:8000")
FINE_SERVICE_URL = os.getenv("FINE_SERVICE_URL", "http://127.0.0.1:8002")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5.0"))

def fetch_thresholds(node_id: str, slot_id: str | None):
    if not THRESHOLD_SERVICE_URL:
        return None, None
    url = THRESHOLD_SERVICE_URL.rstrip("/") + f"/thresholds/{node_id}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return data.get("thresholds", {}), data

def call_fine_service(payload: dict) -> dict | None:
    if not FINE_SERVICE_URL:
        return None
    url = FINE_SERVICE_URL.rstrip("/") + "/fine/eval"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

@app.on_event("startup")
def startup():
    ensure_events_table()

@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": time.time()}

@app.post("/detect/eval", response_model=DetectResponse)
def detect_eval(req: DetectRequest):
    thresholds = None
    tmeta = {}
    node_meta = {}
    if req.node_id:
        try:
            thresholds, node_meta = fetch_thresholds(req.node_id, req.slot_id)
            tmeta = {"source": "threshold_service", **node_meta}
        except Exception:
            thresholds = None

    if not thresholds:
        thresholds, tmeta = load_thresholds(req.slot_id)
        if thresholds:
            tmeta = {"source": "local_db", **tmeta}
        else:
            raise HTTPException(status_code=503, detail="No thresholds found")

    values = {k: float(v) for k, v in req.values.items()}
    exceed, ratio = compute_exceed(values, thresholds)
    any_exceed = any(exceed.values()) if exceed else False
    level = decide_level(any_exceed, ratio)

    event_id = str(uuid.uuid4())
    resp = {
        "event_id": event_id,
        "slot_id": req.slot_id,
        "level": level,
        "any_exceed": any_exceed,
        "exceed": exceed,
        "exceed_ratio": ratio,
        "threshold_ref": tmeta,
        "evidence": {"values": values, "ts": req.ts},
        "fine": None,
    }

    # 超标才跑精细化检测（先用 stub，占位）
    if any_exceed:
        fine_payload = {
            "event_id": event_id,
            "node_type": node_meta.get("node_type", "default"),
            "slot_id": req.slot_id,
            "ts": req.ts,
            "values": values,
            "exceed_ratio": ratio,
        }
        try:
            resp["fine"] = call_fine_service(fine_payload)
        except Exception:
            resp["fine"] = fine_detect_stub(values, ratio)

    # 写入本地同一个 .db 文件（events 表）
    save_event(event_id, req.slot_id, level, any_exceed, resp)
    return resp
