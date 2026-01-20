# app/logic.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
import math
import time
import uuid

DEFAULT_CFG = {
    # 判定阈值（相对残差比例）
    # residual_ratio = (q_out - q_in - storage_flow) / max(q_in, eps)
    "tol_ratio": 0.10,        # 10% 以内认为可接受（可按你实验调整）
    "watch_on": 0.60,
    "alert_on": 0.85,

    # EWMA / CUSUM（用于“持续不闭合”更敏感）
    "alpha": 0.05,
    "cusum_k": 0.5,
    "cusum_h": 6.0,

    # 数据质量门控
    "dq_min": 0.6,

    # 事件
    "event_on": 0.85,
    "event_off": 0.60,
    "event_close_points": 3,
    "min_event_seconds": 120,   # 漏排一般不需要秒级；这里默认 2 分钟
}

def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
        if not math.isfinite(x):
            return None
        return x
    except Exception:
        return None

def _parse_ts(v: Any) -> float:
    x = _to_float(v)
    if x is None:
        return time.time()
    return x / 1000.0 if x > 1e12 else x

def _clip01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)

@dataclass
class SegmentState:
    mean: float = 0.0
    var: float = 1e-6
    s_pos: float = 0.0
    s_neg: float = 0.0
    alpha: float = DEFAULT_CFG["alpha"]

    # event
    open_event_id: Optional[str] = None
    open_start_ts: Optional[float] = None
    peak_score: float = 0.0
    below_off_count: int = 0

SEG_STATES: Dict[str, SegmentState] = {}
EVENTS: Dict[str, Dict[str, Any]] = {}

def _state(seg_id: str) -> SegmentState:
    if seg_id not in SEG_STATES:
        SEG_STATES[seg_id] = SegmentState()
    return SEG_STATES[seg_id]

def _ewma_update(st: SegmentState, x: float, alpha: float) -> Tuple[float, float]:
    a = alpha
    mu = st.mean
    var = st.var

    mu_new = (1 - a) * mu + a * x
    var_new = (1 - a) * var + a * (x - mu_new) ** 2

    st.mean = mu_new
    st.var = max(var_new, 1e-6)
    return mu_new, math.sqrt(st.var)

def _cusum_update(st: SegmentState, z: float, k: float, h: float) -> float:
    sp = st.s_pos
    sn = st.s_neg
    sp = max(0.0, sp + (z - k))
    sn = min(0.0, sn + (z + k))
    st.s_pos = sp
    st.s_neg = sn
    g = max(sp, -sn)
    return min(1.0, g / h)

def _level_from_score(score: float, dq_ok: bool, cfg: Dict[str, Any]) -> str:
    if not dq_ok and score > 0:
        return "WATCH"
    if score >= cfg["alert_on"]:
        return "ALERT"
    if score >= cfg["watch_on"]:
        return "WATCH"
    return "OK"

def _manage_event(st: SegmentState, seg_id: str, ts: float, score: float, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if st.open_event_id is None:
        if score >= cfg["event_on"]:
            eid = str(uuid.uuid4())
            st.open_event_id = eid
            st.open_start_ts = ts
            st.peak_score = score
            st.below_off_count = 0
            EVENTS[eid] = {
                "event_id": eid,
                "segment_id": seg_id,
                "start_ts": ts,
                "end_ts": None,
                "peak_score": score,
                "status": "OPEN",
            }
            return EVENTS[eid]
        return None

    # event open
    st.peak_score = max(st.peak_score, score)
    EVENTS[st.open_event_id]["peak_score"] = st.peak_score

    if score < cfg["event_off"]:
        st.below_off_count += 1
    else:
        st.below_off_count = 0

    if st.below_off_count >= cfg["event_close_points"]:
        start_ts = st.open_start_ts or ts
        dur = ts - start_ts
        if dur >= cfg["min_event_seconds"]:
            EVENTS[st.open_event_id]["end_ts"] = ts
            EVENTS[st.open_event_id]["status"] = "CLOSED"
            out = EVENTS[st.open_event_id]
        else:
            EVENTS.pop(st.open_event_id, None)
            out = None

        st.open_event_id = None
        st.open_start_ts = None
        st.peak_score = 0.0
        st.below_off_count = 0
        return out

    return EVENTS[st.open_event_id]

def check_leakage_one(sample: Dict[str, Any], cfg_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    t0 = time.perf_counter()

    cfg = dict(DEFAULT_CFG)
    if cfg_override:
        cfg.update(cfg_override)

    seg_id = str(sample.get("segment_id") or sample.get("seg_id") or "SEG_UNKNOWN")
    ts = _parse_ts(sample.get("ts"))

    dq = _to_float(sample.get("dq_score"))
    if dq is None:
        dq = 1.0
    dq_ok = dq >= cfg["dq_min"]

    # window length (seconds), used only if delta_volume present
    window_s = _to_float(sample.get("window_s"))
    if window_s is None or window_s <= 0:
        window_s = 60.0

    # upstream flows
    upstream = sample.get("upstream") or []
    q_in = 0.0
    up_detail = []
    for u in upstream:
        nid = u.get("node_id")
        q = _to_float(u.get("flow"))
        if q is None:
            continue
        q_in += q
        up_detail.append({"node_id": nid, "flow": q})

    # downstream flow
    down = sample.get("downstream") or {}
    down_id = down.get("node_id")
    q_out = _to_float(down.get("flow"))

    # storage term: allow either storage_flow (already in flow unit) or delta_volume (m3) -> flow equiv
    storage_flow = _to_float(sample.get("storage_flow"))
    if storage_flow is None:
        dv = _to_float(sample.get("delta_volume"))
        if dv is None:
            storage_flow = 0.0
        else:
            storage_flow = dv / window_s  # volume change to equivalent flow

    missing = []
    if q_out is None:
        missing.append("downstream.flow")
    if len(up_detail) == 0:
        missing.append("upstream[].flow")

    # If missing critical flow, return early (but still include compute_ms)
    if q_out is None or len(up_detail) == 0:
        out = {
            "segment_id": seg_id,
            "ts": ts,
            "level": "WATCH",
            "leak_score": 0.0,
            "leak_type": "UNKNOWN",
            "balance": {
                "q_in": q_in if len(up_detail) else None,
                "q_out": q_out,
                "storage_flow": storage_flow,
                "residual": None,
                "residual_ratio": None,
            },
            "evidence": {"dq_score": dq, "missing_fields": missing},
            "event": None,
        }
        out["compute_ms"] = (time.perf_counter() - t0) * 1000.0
        return out

    # balance residual (positive means "more out than in", negative means "less out than in")
    # residual = q_out - q_in - storage_flow
    residual = float(q_out) - float(q_in) - float(storage_flow)

    eps = 1e-6
    denom = max(abs(q_in), eps)
    residual_ratio = residual / denom

    tol = float(cfg["tol_ratio"])
    # ratio_excess: how much beyond tolerance
    ratio_excess = max(0.0, (abs(residual_ratio) - tol) / max(tol, eps))
    ratio_score = _clip01(ratio_excess)  # >= tol -> starts rising, then clips

    # persistent evidence via EWMA + CUSUM on residual
    st = _state(seg_id)
    mu, sd = _ewma_update(st, residual, cfg["alpha"])
    z = (residual - mu) / (sd + 1e-6)
    cp = _cusum_update(st, z, cfg["cusum_k"], cfg["cusum_h"])

    # fuse scores
    # ratio_score catches "instant imbalance"; cp catches "persistent imbalance"
    leak_score = _clip01(0.45 * ratio_score + 0.55 * cp)

    # type
    if abs(residual_ratio) <= tol:
        leak_type = "OK"
    else:
        leak_type = "LOSS" if residual_ratio < -tol else "GAIN"

    level = _level_from_score(leak_score, dq_ok, cfg)
    event = _manage_event(st, seg_id, ts, leak_score, cfg)

    out = {
        "segment_id": seg_id,
        "ts": ts,
        "level": level,
        "leak_score": leak_score,
        "leak_type": leak_type,  # LOSS: 可能外泄/漏失; GAIN: 可能入渗/外源进入
        "balance": {
            "q_in": q_in,
            "q_out": float(q_out),
            "storage_flow": float(storage_flow),
            "residual": residual,
            "residual_ratio": residual_ratio,
            "tol_ratio": tol,
        },
        "evidence": {
            "dq_score": dq,
            "ratio_score": ratio_score,
            "cp_score": cp,
            "ewma_mu": mu,
            "ewma_sd": sd,
            "z": z,
            "upstream_used": up_detail,
            "downstream_used": {"node_id": down_id, "flow": float(q_out)},
            "window_s": window_s,
        },
        "event": event,
    }

    out["compute_ms"] = (time.perf_counter() - t0) * 1000.0
    return out
