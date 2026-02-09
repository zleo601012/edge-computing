import time
from fastapi import FastAPI, HTTPException
from .models import FineRequest, FineResponse
from .db import ensure_fine_table, save_fine, read_fine
from .fine_logic import fine_detect

app = FastAPI(title="svc-fine-detect", version="1.0.0")

@app.on_event("startup")
def startup():
    ensure_fine_table()

@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": time.time()}

@app.post("/fine/eval", response_model=FineResponse)
def fine_eval(req: FineRequest):
    values = {k: float(v) for k, v in req.values.items()}
    series = None
    if req.series:
        series = [{k: float(v) for k, v in item.items()} for item in req.series]

    result = fine_detect(
        node_type=req.node_type,
        values=values,
        exceed_ratio={k: float(v) for k, v in req.exceed_ratio.items()},
        series=series,
    )

    out = {
        "event_id": req.event_id,
        "slot_id": req.slot_id,
        **result
    }

    # 写回同一个 .db（fine_events 表）
    save_fine(
        event_id=req.event_id,
        slot_id=req.slot_id,
        pollution_type=result["pollution_type"],
        severity_score=result["severity_score"],
        confidence=result["confidence"],
        result=out
    )
    return out

@app.get("/fine/result")
def fine_result(event_id: str):
    data = read_fine(event_id)
    if not data:
        raise HTTPException(status_code=404, detail="not found")
    return data
