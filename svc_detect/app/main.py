import os
import time
import uuid
from typing import Dict, Optional, Tuple

import httpx
from fastapi import FastAPI

from .db import ensure_events_table, load_thresholds, save_event
from .models import DetectRequest, DetectResponse
from .rules import compute_exceed, decide_level, fine_detect_stub

app = FastAPI(title="svc-detect", version="1.0.0")
THRESHOLD_SERVICE_URL = os.getenv("THRESHOLD_SERVICE_URL", "http://127.0.0.1:8000")
FINE_SERVICE_URL = os.getenv("FINE_SERVICE_URL", "http://127.0.0.1:8002")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5.0"))


def _safe_values(values: Dict[str, object]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in (values or {}).items():
        try:
            out[k] = float(v)
        except Exception:
            continue
    return out


def fetch_thresholds(node_id: str, slot_id: Optional[str]) -> Tuple[Optional[Dict[str, object]], Optional[Dict[str, object]]]:
    _ = slot_id  # reserved for future threshold-service API extension
    if not THRESHOLD_SERVICE_URL:
        return None, None
    url = THRESHOLD_SERVICE_URL.rstrip("/") + f"/thresholds/{node_id}"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return data.get("thresholds", {}), data


def call_fine_service(payload: Dict[str, object]) -> Optional[Dict[str, object]]:
    if not FINE_SERVICE_URL:
        return None
    url = FINE_SERVICE_URL.rstrip("/") + "/fine/eval"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


@app.on_event("startup")
def startup() -> None:
    ensure_events_table()


@app.get("/healthz")
def healthz() -> Dict[str, object]:
    return {"ok": True, "ts": time.time()}


@app.post("/detect/eval", response_model=DetectResponse)
def detect_eval(req: DetectRequest) -> Dict[str, object]:
    thresholds = None
    tmeta: Dict[str, object] = {}
    node_meta: Dict[str, object] = {}

    if req.node_id:
        try:
            thresholds, node_meta = fetch_thresholds(req.node_id, req.slot_id)
            tmeta = {"source": "threshold_service", **(node_meta or {})}
        except Exception:
            thresholds = None

    if not thresholds:
        try:
            thresholds, tmeta = load_thresholds(req.slot_id)
        except Exception as e:
            thresholds, tmeta = {}, {"stale": True, "reason": f"local_threshold_load_error: {e!r}"}

        if thresholds:
            tmeta = {"source": "local_db", **tmeta}
        else:
            event_id = str(uuid.uuid4())
            safe_vals = _safe_values(req.values)
            warmup_resp: Dict[str, object] = {
                "event_id": event_id,
                "slot_id": req.slot_id,
                "level": "WARMUP",
                "any_exceed": False,
                "exceed": {k: False for k in safe_vals.keys()},
                "exceed_ratio": {k: 0.0 for k in safe_vals.keys()},
                "threshold_ref": {"source": "unavailable", **tmeta},
                "evidence": {"values": safe_vals, "ts": req.ts},
                "fine": None,
            }
            try:
                save_event(event_id, req.slot_id, "WARMUP", False, warmup_resp)
            except Exception:
                pass
            return warmup_resp

    values = _safe_values(req.values)
    exceed, ratio = compute_exceed(values, thresholds or {})
    any_exceed = any(exceed.values()) if exceed else False
    level = decide_level(any_exceed, ratio)

    event_id = str(uuid.uuid4())
    resp: Dict[str, object] = {
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

    try:
        save_event(event_id, req.slot_id, level, any_exceed, resp)
    except Exception:
        pass
    return resp
