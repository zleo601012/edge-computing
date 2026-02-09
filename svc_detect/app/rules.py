from typing import Dict, Tuple, Union, Optional

ThresholdValue = Union[float, Tuple[float, float], Dict[str, Optional[float]]]

def compute_exceed(values: Dict[str, float], thresholds: Dict[str, ThresholdValue]):
    exceed: Dict[str, bool] = {}
    ratio: Dict[str, float] = {}

    for k, v in values.items():
        if k not in thresholds:
            exceed[k] = False
            ratio[k] = 0.0
            continue

        t = thresholds[k]
        # 支持 {low, high} 结构（来自阈值服务）
        if isinstance(t, dict):
            low = t.get("low")
            high = t.get("high")
            if low is not None and high is not None:
                t = (float(low), float(high))
            elif low is not None:
                t = ("__lower__", float(low))
            elif high is not None:
                t = float(high)
            else:
                exceed[k] = False
                ratio[k] = 0.0
                continue
        # 双边阈值（例如 pH）
        if isinstance(t, (list, tuple)) and len(t) == 2:
            if t[0] == "__lower__":
                lo = float(t[1])
                bad = v < lo
                exceed[k] = bad
                ratio[k] = (lo - v) / max(abs(lo), 1e-9) if bad else 0.0
            else:
                lo, hi = float(t[0]), float(t[1])
                bad = (v < lo) or (v > hi)
                exceed[k] = bad
                if v < lo:
                    ratio[k] = (lo - v) / max(abs(lo), 1e-9)
                elif v > hi:
                    ratio[k] = (v - hi) / max(abs(hi), 1e-9)
                else:
                    ratio[k] = 0.0
        # 单边上限阈值（COD/BOD/TN/NH3N 等）
        else:
            up = float(t)
            bad = v > up
            exceed[k] = bad
            ratio[k] = (v / max(up, 1e-9)) if up > 0 else (1.0 if bad else 0.0)

    return exceed, ratio

def decide_level(any_exceed: bool, ratio: Dict[str, float]) -> str:
    if not any_exceed:
        return "OK"
    mx = max(ratio.values()) if ratio else 0.0
    if mx >= 1.5:
        return "ALERT"
    return "WARN"

def fine_detect_stub(values: Dict[str, float], ratio: Dict[str, float]) -> Dict[str, object]:
    # 占位：你后面换成真实“精细化检测”算法/服务即可
    mx = max(ratio.values()) if ratio else 0.0
    if mx >= 1.5:
        lvl = "HEAVY"
    elif mx >= 1.2:
        lvl = "MEDIUM"
    else:
        lvl = "LIGHT"

    # 粗分类占位：按超标指标拼接
    types = []
    for k, r in ratio.items():
        if r > 1.0:
            types.append(k)
    return {
        "status": "DONE",
        "severity_score": round(min(1.0, max(0.0, mx - 1.0)), 4),
        "pollution_level": lvl,
        "pollution_type": "+".join(types) if types else "UNKNOWN",
        "confidence": 0.6
    }
