from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import math

def _is_bad_number(x: float) -> bool:
    return math.isnan(x) or math.isinf(x)

def data_quality_checks(values: Dict[str, float]) -> Tuple[bool, List[str]]:
    """返回 (dq_ok, reasons)"""
    reasons = []
    for k, v in values.items():
        if _is_bad_number(v):
            reasons.append(f"{k}:nan_or_inf")
        if k.lower() == "ph":
            if v < 0 or v > 14:
                reasons.append("pH:out_of_range")
        # 绝大多数浓度指标不应为负
        if k.lower() != "ph" and v < 0:
            reasons.append(f"{k}:negative")
    return (len(reasons) == 0), reasons

def compute_persistence(series: Optional[List[Dict[str, float]]],
                        exceed_ratio: Dict[str, float]) -> int:
    """
    粗略的“持续性”估计：
    - 如果没提供 series：返回 1
    - 如果提供：统计窗口内超标(>1.0)点的连续段长度（取末尾连续）
    """
    if not series:
        return 1

    # 只看“当前已经超标的指标”
    keys = [k for k, r in exceed_ratio.items() if r > 1.0]
    if not keys:
        return 1

    consec = 0
    # 从序列末尾往前数连续超标
    for item in reversed(series):
        ok = False
        for k in keys:
            v = float(item.get(k, 0.0))
            # 这里不知道阈值本体，所以用 exceed_ratio 的键来近似：
            # 若 k 在 item 中，并且该点相对本点不明显回落，则当作持续（保守）
            if k in item and v > 0:
                ok = True
        if ok:
            consec += 1
        else:
            break
    return max(1, consec)

def classify_type(node_type: str, exceed_ratio: Dict[str, float], dq_ok: bool, dq_reasons: List[str],
                  persistence: int) -> str:
    if not dq_ok:
        return "SENSOR_FAULT"

    # 指标超标集合
    bad = {k for k, r in exceed_ratio.items() if r > 1.0}

    # pH 冲击
    if "pH" in bad or "ph" in {x.lower() for x in bad}:
        # 如果只有 pH 超标
        if len(bad) == 1:
            return "PH_SHOCK"

    # 泵站：短时单指标尖峰更可能是工况
    if node_type == "pump" and persistence <= 1 and len(bad) == 1:
        return "PUMP_OPERATION_SPIKE"

    # 有机负荷
    if "COD" in bad and "BOD" in bad:
        return "ORGANIC_LOAD"

    # 氮负荷
    if ("TN" in bad) or ("NH3N" in bad) or ("NH4" in bad):
        # 若氮相关为主
        if bad.issubset({"TN", "NH3N", "NH4"}):
            return "NITROGEN_LOAD"
        return "NITROGEN_MIXED"

    if len(bad) >= 3:
        return "MIXED_POLLUTION"

    return "UNKNOWN"

def severity_and_confidence(node_type: str, exceed_ratio: Dict[str, float], persistence: int,
                            dq_ok: bool) -> Tuple[float, float, str]:
    """
    severity_score: 0~1
    confidence: 0~1
    """
    if not exceed_ratio:
        return 0.0, 0.2, "LIGHT"

    mx = max(exceed_ratio.values())
    cnt = sum(1 for r in exceed_ratio.values() if r > 1.0)

    # 节点类型权重（可在论文里解释：泵站对尖峰降权）
    type_w = {
        "enterprise": 1.10,
        "residential": 1.00,
        "trunk": 1.05,
        "pump": 0.85,
    }.get(node_type, 1.0)

    # 严重度：超标倍数 + 多指标 + 持续性
    score = (max(0.0, mx - 1.0) * 0.55) + (min(3, cnt) / 3.0 * 0.25) + (min(3, persistence) / 3.0 * 0.20)
    score *= type_w
    score = max(0.0, min(1.0, score))

    level = "HEAVY" if score >= 0.75 else "MEDIUM" if score >= 0.4 else "LIGHT"

    # 置信度：有窗口序列（持续性>1）更高；数据质量差则降低
    conf = 0.55
    if persistence >= 2:
        conf += 0.20
    if cnt >= 2:
        conf += 0.10
    if not dq_ok:
        conf -= 0.35
    conf = max(0.05, min(0.95, conf))

    return score, conf, level

def fine_detect(node_type: str, values: Dict[str, float], exceed_ratio: Dict[str, float],
                series: Optional[List[Dict[str, float]]]) -> Dict[str, object]:
    dq_ok, dq_reasons = data_quality_checks(values)
    persistence = compute_persistence(series, exceed_ratio)
    ptype = classify_type(node_type, exceed_ratio, dq_ok, dq_reasons, persistence)
    severity, conf, plevel = severity_and_confidence(node_type, exceed_ratio, persistence, dq_ok)

    # 事件确认：如果持续性>=2 或 多指标超标>=2 认为确认
    bad_cnt = sum(1 for r in exceed_ratio.values() if r > 1.0)
    confirmed = (persistence >= 2) or (bad_cnt >= 2)
    if ptype == "SENSOR_FAULT":
        confirmed = False  # 传感器问题不当作污染事件

    return {
        "is_confirmed_event": confirmed,
        "severity_score": round(severity, 4),
        "pollution_level": plevel,
        "pollution_type": ptype,
        "confidence": round(conf, 4),
        "evidence": {
            "dq_ok": dq_ok,
            "dq_reasons": dq_reasons,
            "persistence_est": persistence,
            "bad_metric_count": bad_cnt,
            "max_exceed_ratio": round(max(exceed_ratio.values()) if exceed_ratio else 0.0, 4),
            "node_type_weighted": True
        }
    }
