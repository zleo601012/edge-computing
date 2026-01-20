# app/main.py
from __future__ import annotations

from typing import Dict, Any, List, Optional
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .logic import check_one

app = FastAPI(title="Pipe Leak Detection Service", version="0.2")


class CheckReq(BaseModel):
    node_id: str = Field(..., description="segment_id / node_id")
    record: Optional[Dict[str, Any]] = None
    records: Optional[List[Dict[str, Any]]] = None
    cfg: Optional[Dict[str, Any]] = None


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/v1/check")
def check(req: CheckReq):
    t_handler0 = time.perf_counter()
    server_recv_ts = time.time()

    if req.record is None and req.records is None:
        raise HTTPException(status_code=400, detail="Provide either 'record' or 'records'.")
    if req.record is not None and req.records is not None:
        raise HTTPException(status_code=400, detail="Provide only one of 'record' or 'records'.")

    # single
    if req.record is not None:
        out = check_one(req.record, req.node_id, req.cfg)
        out["server_recv_ts"] = server_recv_ts
        out["handler_ms"] = (time.perf_counter() - t_handler0) * 1000.0
        return out

    # batch
    results = [check_one(r, req.node_id, req.cfg) for r in (req.records or [])]
    if not results:
        raise HTTPException(status_code=400, detail="'records' is empty.")

    rank = {"UNKNOWN": 0, "OK": 1, "ALERT": 2}
    worst = max(results, key=lambda x: rank.get(x.get("level", "UNKNOWN"), 0))

    return {
        "node_id": req.node_id,
        "server_recv_ts": server_recv_ts,
        "handler_ms": (time.perf_counter() - t_handler0) * 1000.0,
        "batch_size": len(results),
        "worst": worst,
        "results": results,
    }
