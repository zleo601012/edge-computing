# app/main.py
from __future__ import annotations
from typing import Dict, Any, Optional, List
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .logic import check_one

app = FastAPI(title="Pump Station Water Quality Service", version="0.1")


class CheckReq(BaseModel):
    station_id: str = Field(..., description="pump station id")
    record: Optional[Dict[str, Any]] = None
    records: Optional[List[Dict[str, Any]]] = None
    limits: Optional[Dict[str, Any]] = None   # 覆盖默认阈值
    cfg: Optional[Dict[str, Any]] = None      # 覆盖算法参数


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

    if req.record is not None:
        out = check_one(req.record, req.station_id, req.limits, req.cfg)
        out["server_recv_ts"] = server_recv_ts
        out["handler_ms"] = (time.perf_counter() - t_handler0) * 1000.0
        return out

    results = [check_one(r, req.station_id, req.limits, req.cfg) for r in (req.records or [])]
    if not results:
        raise HTTPException(status_code=400, detail="'records' is empty.")

    rank = {"OK": 0, "WATCH": 1, "ALERT": 2, "UNKNOWN": -1}
    worst = max(results, key=lambda x: rank.get(x.get("level", "UNKNOWN"), -1))

    return {
        "station_id": req.station_id,
        "server_recv_ts": server_recv_ts,
        "handler_ms": (time.perf_counter() - t_handler0) * 1000.0,
        "batch_size": len(results),
        "worst": worst,
        "results": results,
    }
