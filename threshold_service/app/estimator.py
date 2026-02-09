from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
from typing import Dict, Optional, Any
import numpy as np

from .profiles import Profile
from .state import infer_node_type

def rule_type(metric: str) -> str:
    m = metric.lower()
    if m == "ph":
        return "two_sided"
    if m.startswith("do") or m == "do_mg_l" or "do_mg" in m:
        return "lower"
    return "upper"

def quantile(arr: np.ndarray, q: float, min_samples: int) -> Optional[float]:
    if arr.size < min_samples:
        return None
    return float(np.quantile(arr, q))

def smooth(old: Optional[float], new: Optional[float], beta: float) -> Optional[float]:
    if new is None:
        return old
    if old is None:
        return new
    return (1 - beta) * old + beta * new

def blend(long_v: Optional[float], short_v: Optional[float], w_long: float) -> Optional[float]:
    if long_v is None and short_v is None:
        return None
    if long_v is None:
        return short_v
    if short_v is None:
        return long_v
    return w_long * long_v + (1 - w_long) * short_v

@dataclass
class NodeEstimator:
    node_id: str
    profile: Profile
    min_samples: int = 10

    counter: int = 0
    short_buf: Dict[str, deque] = field(default_factory=dict)
    long_buf: Dict[str, deque] = field(default_factory=dict)

    long_thr: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)   # 慢更新
    thr: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)        # 最终阈值

    def _ensure_metric(self, metric: str) -> None:
        if metric not in self.short_buf:
            self.short_buf[metric] = deque(maxlen=self.profile.short_window)
            self.long_buf[metric] = deque(maxlen=self.profile.long_window)
            self.long_thr[metric] = {"low": None, "high": None}
            self.thr[metric] = {"low": None, "high": None}

    def _compute_short(self) -> Dict[str, Dict[str, Optional[float]]]:
        out: Dict[str, Dict[str, Optional[float]]] = {}
        for m, dq in self.short_buf.items():
            arr = np.asarray(dq, dtype=float)
            kind = rule_type(m)
            low = high = None
            if kind == "upper":
                high = quantile(arr, self.profile.q_high, self.min_samples)
            elif kind == "lower":
                low = quantile(arr, self.profile.q_low, self.min_samples)
            else:
                low = quantile(arr, self.profile.q_low, self.min_samples)
                high = quantile(arr, self.profile.q_high, self.min_samples)
            out[m] = {"low": low, "high": high}
        return out

    def _recompute_long(self) -> None:
        for m, dq in self.long_buf.items():
            arr = np.asarray(dq, dtype=float)
            kind = rule_type(m)
            low = high = None
            if kind == "upper":
                high = quantile(arr, self.profile.q_high, self.min_samples)
            elif kind == "lower":
                low = quantile(arr, self.profile.q_low, self.min_samples)
            else:
                low = quantile(arr, self.profile.q_low, self.min_samples)
                high = quantile(arr, self.profile.q_high, self.min_samples)
            self.long_thr[m] = {"low": low, "high": high}

    def ingest_one(self, values: Dict[str, float]) -> Dict[str, Dict[str, Optional[float]]]:
        # 1) 更新窗口
        for m, v in values.items():
            if v is None:
                continue
            self._ensure_metric(m)
            self.short_buf[m].append(float(v))
            self.long_buf[m].append(float(v))

        self.counter += 1

        # 2) 短期阈值每次都算
        short_thr = self._compute_short()

        # 3) 长期阈值按频率重算（每60次≈1小时一次）
        if self.counter % self.profile.long_recompute_every == 0:
            self._recompute_long()

        # 4) 融合 + 平滑
        for m in self.short_buf.keys():
            raw_low = blend(self.long_thr[m]["low"], short_thr[m]["low"], self.profile.w_long)
            raw_high = blend(self.long_thr[m]["high"], short_thr[m]["high"], self.profile.w_long)
            self.thr[m]["low"] = smooth(self.thr[m]["low"], raw_low, self.profile.smooth_beta)
            self.thr[m]["high"] = smooth(self.thr[m]["high"], raw_high, self.profile.smooth_beta)

        return self.thr


class EstimatorManager:
    """一个服务同时管理多个 node_id，每个 node_id 独立窗口与阈值。"""
    def __init__(self, profiles_by_type: Dict[str, Profile], default_profile: Profile):
        self.profiles_by_type = profiles_by_type
        self.default_profile = default_profile
        self.nodes: Dict[str, NodeEstimator] = {}

    def get_or_create(self, node_id: str) -> NodeEstimator:
        if node_id in self.nodes:
            return self.nodes[node_id]
        node_type = infer_node_type(node_id)
        profile = self.profiles_by_type.get(node_type, self.default_profile)
        est = NodeEstimator(node_id=node_id, profile=profile)
        self.nodes[node_id] = est
        return est
