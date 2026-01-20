# app/logic.py
from __future__ import annotations

from typing import Dict, Any, Optional, Tuple, List
import math
import time
import uuid

# -----------------------------------------------------------------------------
# In-memory state
# -----------------------------------------------------------------------------
# Per-segment EWMA stats for residual_ratio
_STATE: Dict[str, Dict[str, Any]] = {}
# Per-segment event state (OPEN/CLOSED)
_EVENTS: Dict[str, Dict[str, Any]] = {}

# -----------------------------------------------------------------------------
# Default config (can be overridden per request)
# -----------------------------------------------------------------------------
DEFAULT_CFG = {
    "tol_ratio": 0.10,        # anomaly if |residual_ratio| > tol_ratio
    "ewma_alpha": 0.05,       # EWMA update factor
    "min_sd": 1e-3,           # minimum std for z-score
    "z_alert": 3.0,           # z-score threshold
    "use_load_check": True,   # if concentration provided, do load cross-check
}

# Concentration aliases -> canonical keys
ALIASES = {
    "cod": "COD",
    "CODcr": "COD",
    "bod": "BOD",
    "BOD5": "BOD",
    "tn": "TN",
    "nh3n": "NH3N",
    "NH3-N": "NH3N",
    "nh3_n": "NH3N",
    "Am": "NH3N",
    "am": "NH3N",
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


def _get_first(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d.get(k) is not None:
            return d.get(k)
    return None


def _norm_key(k: str) -> str:
    return ALIASES.get(k, k)


def _extract_q_in(record: Dict[str, Any]) -> Optional[float]:
    # 1) direct field
    q = _to_float(_get_first(record, "q_in", "Q_in", "flow_in", "qin", "inflow"))
    if q is not None:
        return q
    # 2) list
    lst = _get_first(record, "upstream_flows", "q_in_list", "qin_list")
    if isinstance(lst, list):
        s = 0.0
        ok = False
        for v in lst:
            fv = _to_float(v)
            if fv is not None:
                s += fv
                ok = True
        return s if ok else None
    # 3) dict
    upstream = _get_first(record, "upstream", "upstreams")
    if isinstance(upstream, dict):
        s = 0.0
        ok = False
        for _, v in upstream.items():
            fv = _to_float(v)
            if fv is not None:
                s += fv
                ok = True
        return s if ok else None
    return None


def _extract_q_out(record: Dict[str, Any]) -> Optional[float]:
    return _to_float(_get_first(record, "q_out", "Q_out", "flow_out", "qout", "outflow"))


def _extract_storage_flow(record: Dict[str, Any]) -> float:
    sf = _to_float(_get_first(record, "storage_flow", "dSdt", "ds_dt"))
    if sf is not None:
        return sf
    return 0.0


def _extract_conc_pair(record: Dict[str, Any]) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Return (cin, cout) in mg/L.
    Supported inputs:
      1) record["cin"] / record["cout"] dict
      2) record["C_in"] / record["C_out"] dict
      3) flat keys like COD_in/COD_out, Am_in/Am_out ...
    """
    cin_raw = _get_first(record, "cin", "C_in", "in_conc")
    cout_raw = _get_first(record, "cout", "C_out", "out_conc")

    cin: Dict[str, float] = {}
    cout: Dict[str, float] = {}

    def load_dict(raw: Any, dst: Dict[str, float]):
        if isinstance(raw, dict):
            for k, v in raw.items():
                kk = _norm_key(str(k))
                fv = _to_float(v)
                if fv is not None:
                    dst[kk] = fv

    load_dict(cin_raw, cin)
    load_dict(cout_raw, cout)

    # flat fallbacks
    for base in ["COD", "BOD", "TN", "NH3N", "Am"]:
        kin = f"{base}_in"
        kout = f"{base}_out"
        vin = _to_float(record.get(kin))
        vout = _to_float(record.get(kout))
        if vin is not None:
            cin[_norm_key(base)] = vin
        if vout is not None:
            cout[_norm_key(base)] = vout

    return cin, cout


def _clamp01(x: float) -> float:
    if x < 0:
        return 0.0
    if x > 1:
        return 1.0
    return x


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


def _ewma_update(mu: float, var: float, x: float, alpha: float) -> Tuple[float, float]:
    mu_new = (1 - alpha) * mu + alpha * x
    diff = x - mu_new
    var_new = (1 - alpha) * var + alpha * (diff * diff)
    return mu_new, var_new


def check_one(
    record: Dict[str, Any],
    segment_id: str,
    cfg_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    One-shot leak detection for a segment.

    Required:
      - q_in and q_out (many aliases supported)

    Optional:
      - storage_flow: estimated dS/dt (helps reduce false alarms)
      - cin/cout: concentrations for load cross-check
    """
    t0 = time.perf_counter()

    # merge cfg
    cfg = dict(DEFAULT_CFG)
    if cfg_override:
        for k, v in cfg_override.items():
            if k in cfg:
                if isinstance(cfg[k], bool):
                    cfg[k] = bool(v)
                else:
                    fv = _to_float(v)
                    if fv is not None:
                        cfg[k] = float(fv)

    ts = _parse_ts(_get_first(record, "ts", "timestamp", "time"))

    q_in = _extract_q_in(record)
    q_out = _extract_q_out(record)
    storage_flow = _extract_storage_flow(record)

    missing: List[str] = []
    if q_in is None:
        missing.append("q_in")
    if q_out is None:
        missing.append("q_out")

    if missing:
        out = {
            "segment_id": segment_id,
            "ts": ts,
            "level": "UNKNOWN",
            "leak_type": "NONE",
            "leak_score": 0.0,
            "missing_fields": missing,
            "evidence": {"msg": "q_in/q_out missing"},
        }
        out["compute_ms"] = (time.perf_counter() - t0) * 1000.0
        return out

    eps = 1e-12
    residual = float(q_in) - float(q_out) - float(storage_flow)
    residual_ratio = residual / (float(q_in) + eps)
    tol_ratio = float(cfg["tol_ratio"])

    # EWMA state per segment
    st = _STATE.get(segment_id)
    if st is None:
        st = {"mu": 0.0, "var": 0.01}
        _STATE[segment_id] = st

    mu = float(st["mu"])
    var = float(st["var"])
    alpha = float(cfg["ewma_alpha"])

    sd = math.sqrt(max(var, float(cfg["min_sd"]) ** 2))
    z = (residual_ratio - mu) / sd

    mu_new, var_new = _ewma_update(mu, var, residual_ratio, alpha)
    st["mu"], st["var"] = mu_new, var_new

    leak_type = "NONE"
    if residual_ratio < -tol_ratio:
        leak_type = "LOSS"
    elif residual_ratio > tol_ratio:
        leak_type = "GAIN"

    # optional load check
    load_evidence: Dict[str, Any] = {}
    load_score = 0.0
    if cfg.get("use_load_check", True):
        cin, cout = _extract_conc_pair(record)
        if cin and cout:
            loads_res: Dict[str, float] = {}
            for k in set(cin.keys()) & set(cout.keys()):
                Lin = float(q_in) * cin[k]
                Lout = float(q_out) * cout[k]
                loads_res[k] = Lin - Lout

            if loads_res:
                same_dir = 0
                for _, rv in loads_res.items():
                    if leak_type == "LOSS" and rv < 0:
                        same_dir += 1
                    if leak_type == "GAIN" and rv > 0:
                        same_dir += 1
                frac = same_dir / max(1, len(loads_res))
                load_score = frac
                load_evidence = {
                    "cin": cin,
                    "cout": cout,
                    "loads_residual": loads_res,
                    "direction_agree": round(frac, 3),
                }

    ratio_score = _clamp01(abs(residual_ratio) / (tol_ratio + eps))
    z_sig = _sigmoid(abs(z) - float(cfg["z_alert"]))

    base = 0.6 * ratio_score + 0.4 * z_sig
    leak_score = base
    if load_evidence:
        leak_score = _clamp01(0.75 * base + 0.25 * load_score)

    # event aggregation
    evt = _EVENTS.get(segment_id)
    if leak_type != "NONE":
        if evt is None or evt.get("status") != "OPEN":
            evt = {
                "event_id": str(uuid.uuid4()),
                "segment_id": segment_id,
                "start_ts": ts,
                "end_ts": None,
                "peak_score": leak_score,
                "status": "OPEN",
            }
            _EVENTS[segment_id] = evt
        else:
            evt["peak_score"] = max(float(evt.get("peak_score", 0.0)), leak_score)
        event_out = dict(evt)
    else:
        if evt is not None and evt.get("status") == "OPEN":
            evt["status"] = "CLOSED"
            evt["end_ts"] = ts
            event_out = dict(evt)
        else:
            event_out = None

    level = "OK" if leak_type == "NONE" else "ALERT"
    out = {
        "segment_id": segment_id,
        "ts": ts,
        "level": level,
        "leak_type": leak_type,
        "leak_score": round(float(leak_score), 3),
        "balance": {
            "q_in": float(q_in),
            "q_out": float(q_out),
            "storage_flow": float(storage_flow),
            "residual": round(residual, 6),
            "residual_ratio": round(residual_ratio, 6),
            "tol_ratio": float(tol_ratio),
        },
        "evidence": {
            "ratio_score": round(float(ratio_score), 3),
            "z": round(float(z), 3),
            "ewma_mu": round(float(mu), 6),
            "ewma_sd": round(float(sd), 6),
            "z_sig": round(float(z_sig), 3),
            **({"load_check": load_evidence} if load_evidence else {}),
        },
        "missing_fields": missing,
        "event": event_out,
    }

    out["compute_ms"] = (time.perf_counter() - t0) * 1000.0
    return out
