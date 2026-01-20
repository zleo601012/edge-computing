# app/logic.py
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple
import math
import time

DEFAULT_LIMITS = {
    "COD": 500.0,
    "TN": 80.0,
    "NH3N": 30.0,
    "pH_min": 6.0,
    "pH_max": 9.0,
    # 可选：如果你想把“流量异常”也作为超排条件之一，再加 flow_max
    # "flow_max": 999999.0,
}

# 小区/生活污水（先只做“是否超标”）：默认采用“入网/入下水道”的工程阈值
# 你也可以在调用时通过 limits_override 覆盖这些阈值。
COMMUNITY_DEFAULT_LIMITS = {
    "COD": 500.0,
    "BOD": 350.0,
    "TN": 70.0,
    "NH3N": 45.0,
    "pH_min": 6.5,
    "pH_max": 9.5,
}

CFG = {
    "dq_min": 0.6,  # 数据质量低于该值时，结论降级为 WATCH
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

def _merge_limits(override: Optional[Dict[str, Any]], base: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    limits = dict(base or DEFAULT_LIMITS)
    if override:
        for k, v in override.items():
            fv = _to_float(v)
            if fv is not None:
                limits[k] = float(fv)
    return limits

def _get_first(record: Dict[str, Any], *keys: str) -> Any:
    """返回 record 中第一个非 None 的键值。"""
    for k in keys:
        if k in record and record.get(k) is not None:
            return record.get(k)
    return None

def _present(record: Dict[str, Any], *keys: str) -> bool:
    return _get_first(record, *keys) is not None


def check_one(
    record: Dict[str, Any],
    node_id: str,
    limits_override: Optional[Dict[str, Any]] = None,
    profile: str = "enterprise",
) -> Dict[str, Any]:
    t0 = time.perf_counter()

    profile_n = (profile or "enterprise").lower()
    if profile_n in ("community", "comm", "xiaoqu", "residential"):
        base_limits = COMMUNITY_DEFAULT_LIMITS
        profile_n = "community"
    else:
        base_limits = DEFAULT_LIMITS
        profile_n = "enterprise"

    limits = _merge_limits(limits_override, base=base_limits)

    ts = _parse_ts(_get_first(record, "ts", "timestamp", "time"))
    dq = _to_float(_get_first(record, "dq_score", "dq", "quality", "quality_score"))
    if dq is None:
        dq = 1.0
    dq_ok = dq >= CFG["dq_min"]

    flow = _to_float(_get_first(record, "flow", "Flow", "q", "Q", "q_out", "Q_out"))
    COD = _to_float(_get_first(record, "COD", "cod", "CODcr", "codcr"))
    TN = _to_float(_get_first(record, "TN", "tn"))
    NH3N = _to_float(_get_first(record, "NH3N", "nh3n", "NH3-N", "nh3_n", "Am", "am"))
    BOD = _to_float(_get_first(record, "BOD", "bod", "BOD5", "bod5"))
    pH = _to_float(_get_first(record, "pH", "ph"))

    # missing_fields：根据 profile 的“常见上报字段”来提示缺失（不影响判定）
    if profile_n == "community":
        missing = []
        if not _present(record, "ts", "timestamp", "time"):
            missing.append("ts")
        if not _present(record, "COD", "cod", "CODcr", "codcr"):
            missing.append("COD")
        if not _present(record, "BOD", "bod", "BOD5", "bod5"):
            missing.append("BOD")
        if not _present(record, "TN", "tn"):
            missing.append("TN")
        if not _present(record, "NH3N", "nh3n", "NH3-N", "nh3_n", "Am", "am"):
            missing.append("NH3N")
        # flow/pH 在很多小区点位可能没有，故不作为必填
    else:
        missing = [k for k in ["ts", "flow", "COD", "TN", "NH3N", "pH"] if record.get(k) is None]

    exceed: Dict[str, Optional[bool]] = {}
    ratio: Dict[str, Optional[float]] = {}

    # COD/TN/NH3N（以及小区的 BOD）：单点超限即“超标点”
    items = [("COD", COD), ("TN", TN), ("NH3N", NH3N)]
    if profile_n == "community":
        items.insert(1, ("BOD", BOD))

    for k, val in items:
        lim = limits.get(k)
        if lim is None:
            exceed[k] = None
            ratio[k] = None
            continue
        if val is None:
            exceed[k] = None
            ratio[k] = None
        else:
            exceed[k] = (val > lim)
            ratio[k] = val / lim

    # pH：范围外算超标点
    if pH is None:
        exceed["pH"] = None
        ratio["pH"] = None
    else:
        bad = (pH < limits["pH_min"]) or (pH > limits["pH_max"])
        exceed["pH"] = bad
        # 用偏离量表示严重程度（越大越严重）
        if pH < limits["pH_min"]:
            ratio["pH"] = limits["pH_min"] - pH
        elif pH > limits["pH_max"]:
            ratio["pH"] = pH - limits["pH_max"]
        else:
            ratio["pH"] = 0.0

    any_exceed = any(v is True for v in exceed.values())

    # 等级：你要的“超排”最干净的定义就是：超限 -> ALERT
    # 如果 dq 低，则降级为 WATCH（提示需要复核）
    if any_exceed and dq_ok:
        level = "ALERT"
    elif any_exceed and (not dq_ok):
        level = "WATCH"
    else:
        level = "OK"

    values_used = {"flow": flow, "COD": COD, "TN": TN, "NH3N": NH3N, "pH": pH}
    if profile_n == "community":
        values_used["BOD"] = BOD

    out = {
        "node_id": node_id,
        "ts": ts,
        "level": level,
        "any_exceed": any_exceed,
        "exceed": exceed,
        "exceed_ratio": ratio,
        "values_used": values_used,
        "dq_score": dq,
        "limits": limits,
        "missing_fields": missing,
    }

    out["compute_ms"] = (time.perf_counter() - t0) * 1000.0  # 新增：耗时（毫秒）
    return out
