# app/logic.py
from __future__ import annotations
from typing import Dict, Any, Optional, List, Tuple
import time
import math

# -------------------------
# 默认“泵站/厂前”工艺保护阈值（可在请求里 limits 覆盖）
# 说明：这不是执法排放标准，而是“厂前进水风险阈值”的一个默认模板
# -------------------------
DEFAULT_LIMITS = {
    "pH_min": 6.0,
    "pH_max": 9.0,
    "COD": 800.0,
    "BOD": 500.0,
    "TN": 80.0,
    "NH3N": 45.0,
}

# -------------------------
# 检测配置（可在请求里 cfg 覆盖）
# -------------------------
DEFAULT_CFG = {
    "ewma_alpha": 0.05,       # 基线更新速度（越大越跟得快）
    "z_watch": 3.0,           # z 超过 -> WATCH
    "z_alert": 5.0,           # z 超过 -> ALERT（冲击很强）
    "min_sd": 1e-6,           # 防止 sd=0
    "delta_ratio_watch": 0.30,# 相对变化超过 30% 才算“冲击”更可信（减少误报）
    "use_flow_load": True,    # 有 flow 时同时看负荷（flow*conc）冲击
    "dq_min": 0.6,            # 数据质量过低则降级为 WATCH
}

# 字段别名（你数据里 Am 代表氨氮的话，自动映射到 NH3N）
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
    "ph": "pH",
}

# 需要维护基线的指标
BASELINE_KEYS = ["COD", "BOD", "TN", "NH3N"]  # pH 用区间判，通常不做 z（你想做也行）

# 每个 station_id 的状态：每个指标保存 mu/var
_STATE: Dict[str, Dict[str, Dict[str, float]]] = {}  # station_id -> metric -> {"mu":..,"var":..}


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


def _norm_record(record: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(record)
    # 把别名字段补到标准字段上（不覆盖已有标准字段）
    for k, v in list(record.items()):
        kk = ALIASES.get(k, k)
        if kk != k and out.get(kk) is None:
            out[kk] = v
    return out


def _merge_limits(override: Optional[Dict[str, Any]]) -> Dict[str, float]:
    limits = dict(DEFAULT_LIMITS)
    if override:
        for k, v in override.items():
            fv = _to_float(v)
            if fv is not None:
                limits[k] = float(fv)
    return limits


def _merge_cfg(override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CFG)
    if override:
        for k, v in override.items():
            if k not in cfg:
                continue
            if isinstance(cfg[k], bool):
                cfg[k] = bool(v)
            else:
                fv = _to_float(v)
                if fv is not None:
                    cfg[k] = float(fv)
    return cfg


def _ewma_update(mu: float, var: float, x: float, alpha: float) -> Tuple[float, float]:
    mu_new = (1 - alpha) * mu + alpha * x
    diff = x - mu_new
    var_new = (1 - alpha) * var + alpha * (diff * diff)
    return mu_new, var_new


def check_one(
    record: Dict[str, Any],
    station_id: str,
    limits_override: Optional[Dict[str, Any]] = None,
    cfg_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    泵站进水水质检测（单条输入->单条输出）：
    - 工程阈值超限（ALERT）
    - 冲击负荷/水质突变（WATCH/ALERT）
    输出包含 compute_ms
    """
    t0 = time.perf_counter()

    cfg = _merge_cfg(cfg_override)
    limits = _merge_limits(limits_override)

    rec = _norm_record(record)

    ts = _parse_ts(_get_first(rec, "ts", "timestamp", "time"))
    dq = _to_float(_get_first(rec, "dq_score", "dq", "quality", "quality_score"))
    if dq is None:
        dq = 1.0

    flow = _to_float(_get_first(rec, "flow", "q", "Q", "q_in", "inflow", "Flow"))

    COD = _to_float(rec.get("COD"))
    BOD = _to_float(rec.get("BOD"))
    TN = _to_float(rec.get("TN"))
    NH3N = _to_float(rec.get("NH3N"))
    pH = _to_float(rec.get("pH"))

    values_used = {"flow": flow, "COD": COD, "BOD": BOD, "TN": TN, "NH3N": NH3N, "pH": pH}

    missing_fields: List[str] = []
    if rec.get("ts") is None and _get_first(rec, "timestamp", "time") is None:
        missing_fields.append("ts")

    # -------------------------
    # 1) 工程阈值超限检查
    # -------------------------
    reasons: List[str] = []
    score = 0.0

    def exceed_score(val: float, lim: float) -> float:
        # 超出比例越大越严重；限制到 [0,1]
        ratio = val / lim if lim > 0 else 10.0
        return max(0.0, min(1.0, ratio - 1.0))

    # pH 区间
    if pH is not None:
        if pH < limits["pH_min"]:
            reasons.append(f"pH:below({pH:.2f}<{limits['pH_min']})")
            score = max(score, 1.0)  # pH 风险直接拉满
        elif pH > limits["pH_max"]:
            reasons.append(f"pH:above({pH:.2f}>{limits['pH_max']})")
            score = max(score, 1.0)
    else:
        missing_fields.append("pH")

    # 其他指标
    for k, v in [("COD", COD), ("BOD", BOD), ("TN", TN), ("NH3N", NH3N)]:
        if v is None:
            missing_fields.append(k)
            continue
        lim = limits.get(k)
        if lim is None:
            continue
        if v > lim:
            reasons.append(f"{k}:exceed({v:.3g}>{lim})")
            score = max(score, exceed_score(v, lim))

    over_limit = any("exceed" in r or "pH:" in r for r in reasons)

    # -------------------------
    # 2) 冲击异常（EWMA 基线 + z-score）
    # -------------------------
    st = _STATE.get(station_id)
    if st is None:
        st = {}
        _STATE[station_id] = st

    z_map: Dict[str, Optional[float]] = {}
    mu_map: Dict[str, Optional[float]] = {}
    sd_map: Dict[str, Optional[float]] = {}
    shock_reasons: List[str] = []
    shock_score = 0.0

    alpha = float(cfg["ewma_alpha"])
    z_watch = float(cfg["z_watch"])
    z_alert = float(cfg["z_alert"])
    min_sd = float(cfg["min_sd"])
    delta_ratio_watch = float(cfg["delta_ratio_watch"])

    # 先做浓度冲击
    for k, v in [("COD", COD), ("BOD", BOD), ("TN", TN), ("NH3N", NH3N)]:
        if v is None:
            z_map[k] = None
            mu_map[k] = None
            sd_map[k] = None
            continue

        m = st.get(k)
        if m is None:
            # 初始化：第一次见到直接建基线，不报冲击
            st[k] = {"mu": float(v), "var": 0.01}
            z_map[k] = 0.0
            mu_map[k] = float(v)
            sd_map[k] = math.sqrt(0.01)
            continue

        mu = float(m["mu"])
        var = float(m["var"])
        sd = math.sqrt(max(var, min_sd**2))
        z = (float(v) - mu) / sd if sd > 0 else 0.0

        # 相对变化约束：变化不明显就不当冲击
        rel = abs(float(v) - mu) / (abs(mu) + 1e-12)

        z_map[k] = float(z)
        mu_map[k] = float(mu)
        sd_map[k] = float(sd)

        if rel >= delta_ratio_watch and abs(z) >= z_watch:
            shock_reasons.append(f"{k}:shock(z={z:.2f},rel={rel:.2f})")
            # 冲击评分：z 超过 watch 越多越接近 1
            shock_score = max(shock_score, min(1.0, (abs(z) - z_watch) / max(1e-9, (z_alert - z_watch))))

        # 更新基线（用当前点更新）
        mu_new, var_new = _ewma_update(mu, var, float(v), alpha)
        m["mu"], m["var"] = mu_new, var_new

    # 再做负荷冲击（有 flow 才做）：Load = flow * concentration
    load_z_map: Dict[str, Optional[float]] = {}
    if cfg.get("use_flow_load", True) and flow is not None and flow > 0:
        # 单独维护 load 的基线（key 用 "COD_load"）
        for k, v in [("COD", COD), ("BOD", BOD), ("TN", TN), ("NH3N", NH3N)]:
            if v is None:
                load_z_map[k] = None
                continue
            load = float(flow) * float(v)
            lk = f"{k}_load"
            m = st.get(lk)
            if m is None:
                st[lk] = {"mu": load, "var": 0.01}
                load_z_map[k] = 0.0
                continue
            mu = float(m["mu"])
            var = float(m["var"])
            sd = math.sqrt(max(var, min_sd**2))
            z = (load - mu) / sd if sd > 0 else 0.0
            load_z_map[k] = float(z)

            rel = abs(load - mu) / (abs(mu) + 1e-12)
            if rel >= delta_ratio_watch and abs(z) >= z_watch:
                shock_reasons.append(f"{k}_load:shock(z={z:.2f},rel={rel:.2f})")
                shock_score = max(shock_score, min(1.0, (abs(z) - z_watch) / max(1e-9, (z_alert - z_watch))))

            mu_new, var_new = _ewma_update(mu, var, load, alpha)
            m["mu"], m["var"] = mu_new, var_new

    # -------------------------
    # 3) 综合等级判定（包含 dq 降级）
    # -------------------------
    level = "OK"
    alarm = 0

    if over_limit:
        level = "ALERT"
        alarm = 1
    elif shock_reasons:
        # 冲击：轻则 WATCH，强则 ALERT
        if shock_score >= 0.8:
            level = "ALERT"
            alarm = 1
        else:
            level = "WATCH"
            alarm = 1

    # 数据质量降级：dq 太低时，不给强结论
    if alarm == 1 and dq < float(cfg["dq_min"]) and level == "ALERT":
        level = "WATCH"

    # 组合 score：超限优先，其次冲击
    score = max(score, shock_score)

    out = {
        "station_id": station_id,
        "ts": ts,
        "level": level,
        "alarm": alarm,
        "score": round(float(score), 3),
        "reasons": reasons + shock_reasons,
        "values_used": values_used,
        "limits": limits,
        "dq_score": dq,
        "missing_fields": sorted(set(missing_fields)),
        "evidence": {
            "ewma": {
                "z": z_map,
                "mu": mu_map,
                "sd": sd_map,
                "load_z": load_z_map if load_z_map else None,
            }
        },
    }

    out["compute_ms"] = (time.perf_counter() - t0) * 1000.0
    return out
