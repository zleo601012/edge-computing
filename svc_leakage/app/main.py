# app/main.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .logic import check_leakage_one, EVENTS

app = FastAPI(title="Leakage Service", version="0.1")

class Req(BaseModel):
    # 你可以只传 sample（单条），也可以传 samples（多条）
    sample: Optional[Dict[str, Any]] = None
    samples: Optional[List[Dict[str, Any]]] = None
    cfg: Optional[Dict[str, Any]] = None  # 可选：覆盖 tol_ratio/alpha/cusum 等

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/v1/check")
def check(req: Req):
    if req.sample is None and req.samples is None:
        raise HTTPException(status_code=400, detail="Provide either 'sample' or 'samples'.")
    if req.sample is not None and req.samples is not None:
        raise HTTPException(status_code=400, detail="Provide only one of 'sample' or 'samples'.")

    if req.sample is not None:
        return check_leakage_one(req.sample, req.cfg)

    t0 = time.perf_counter()
    results = [check_leakage_one(s, req.cfg) for s in (req.samples or [])]
    if not results:
        raise HTTPException(status_code=400, detail="'samples' is empty.")

    rank = {"OK": 0, "WATCH": 1, "ALERT": 2}
    worst = max(results, key=lambda x: (rank.get(x["level"], 0), x.get("leak_score", 0.0)))

    out = {
        "batch_size": len(results),
        "worst": worst,
        "results": results,
        "batch_compute_ms": (time.perf_counter() - t0) * 1000.0,
    }
    return out

@app.get("/v1/events")
def events(limit: int = 50):
    evs = sorted(EVENTS.values(), key=lambda x: x["start_ts"], reverse=True)[:limit]
    return {"events": evs}
