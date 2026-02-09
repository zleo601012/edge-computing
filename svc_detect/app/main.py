import uuid, time
from fastapi import FastAPI, HTTPException
from .models import DetectRequest, DetectResponse
from .db import ensure_events_table, load_thresholds, save_event
from .rules import compute_exceed, decide_level, fine_detect_stub

app = FastAPI(title="svc-detect", version="1.0.0")

@app.on_event("startup")
def startup():
    ensure_events_table()

@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": time.time()}

@app.post("/detect/eval", response_model=DetectResponse)
def detect_eval(req: DetectRequest):
    thresholds, tmeta = load_thresholds(req.slot_id)
    if not thresholds:
        raise HTTPException(status_code=503, detail="No thresholds found in local DB")

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
        resp["fine"] = fine_detect_stub(values, ratio)

    # 写入本地同一个 .db 文件（events 表）
    save_event(event_id, req.slot_id, level, any_exceed, resp)
    return resp
