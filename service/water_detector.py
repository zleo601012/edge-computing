# detector.py
from __future__ import annotations

import time
import math
import random
from dataclasses import dataclass
from collections import deque
from statistics import median
from typing import Dict, Any, Tuple, Optional, List


# -----------------------------
# 1) Context / State (kept across calls)
# -----------------------------

TARGET_FIELDS = ("Am", "BOD", "COD", "TN")  # 你要判断超标的字段，可扩展


@dataclass
class DetectionContext:
    """
    Keep rolling windows for robust statistics.
    """
    window_size: int = 120  # 5s一条，120条=10分钟
    history: Dict[str, deque] = None

    def __post_init__(self):
        if self.history is None:
            self.history = {k: deque(maxlen=self.window_size) for k in TARGET_FIELDS}


# -----------------------------
# 2) Robust stats + math utilities
# -----------------------------

def _safe_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
        if math.isfinite(v):
            return v
        return None
    except Exception:
        return None


def _sigmoid(x: float) -> float:
    # stable sigmoid
    if x >= 60:
        return 1.0
    if x <= -60:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _mad(vals: List[float], med: float) -> float:
    # median absolute deviation + eps to avoid division by zero
    dev = [abs(v - med) for v in vals]
    return (median(dev) if dev else 0.0) + 1e-9


def _robust_z(x: float, window: deque) -> float:
    vals = list(window)
    if len(vals) < 8:
        return 0.0
    med = median(vals)
    m = _mad(vals, med)
    # 0.6745 makes MAD comparable to std for normal dist
    return 0.6745 * (x - med) / m


def _percentile(sorted_vals: List[float], p: float) -> float:
    # p in [0,1]
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    idx = (n - 1) * p
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    w = idx - lo
    return sorted_vals[lo] * (1 - w) + sorted_vals[hi] * w


# -----------------------------
# 3) Core: one task computation (time-budgeted 1–3 seconds)
# -----------------------------

def compute_overlimit_task(
    row: Dict[str, Any],
    ctx: DetectionContext,
    *,
    limits: Dict[str, float],
    target_sec: float = 2.0,
    min_sec: float = 1.0,
    max_sec: float = 3.0,
    noise_sigma_rel: float = 0.03,
    alarm_prob_mean: float = 0.90,
    alarm_prob_p05: float = 0.60,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Precision-first exceedance detection with runtime constrained to [min_sec, max_sec].

    Inputs
    - row: one record from your CSV (dict-like)
    - ctx: persistent rolling window state
    - limits: exceedance limits for each target field (MUST be set by you)
    - target_sec/min_sec/max_sec: runtime budget control

    Output dict includes:
    - alarm: bool
    - prob_mean, prob_p05, prob_p95
    - elapsed_sec
    - reasons: list of strings
    - used_samples: actual Monte Carlo samples performed
    - values: parsed numeric values
    """

    if seed is not None:
        random.seed(seed)

    # 1) Parse numeric values of interest
    values: Dict[str, float] = {}
    for k in TARGET_FIELDS:
        v = _safe_float(row.get(k))
        if v is not None:
            values[k] = v

    # 2) Define a risk scoring function (logit) for one noisy draw
    #    This is intentionally "meaningful heavy": exceed ratio + robust anomaly (z-score)
    #    You can tune weights later.
    def risk_logit(noisy_vals: Dict[str, float]) -> Tuple[float, List[str]]:
        reasons: List[str] = []
        logit = -2.2  # bias (more negative => more conservative alarms)

        for k in TARGET_FIELDS:
            x = noisy_vals.get(k)
            lim = limits.get(k)
            if x is None or lim is None:
                continue

            exceed = max(0.0, (x - lim) / max(lim, 1e-9))
            z = _robust_z(x, ctx.history[k])

            # only count significant anomaly part
            z_pos = max(0.0, z - 2.0)

            # weights (tunable)
            logit += 2.0 * exceed
            logit += 1.2 * (z_pos / 3.0)

            if exceed > 0:
                reasons.append(f"{k}:exceed({exceed:.2f})")
            elif z_pos > 0:
                reasons.append(f"{k}:anomaly(z={z:.2f})")

        return logit, reasons

    # 3) Time-budgeted Monte Carlo
    t0 = time.perf_counter()
    probs: List[float] = []
    reasons_pool: List[str] = []
    used = 0

    # batch helps reduce per-loop overhead a bit
    batch = 200

    # guardrails for runtime params
    target = max(min_sec, min(target_sec, max_sec))
    min_s = max(0.0, min_sec)
    max_s = max(min_s, max_sec)

    while True:
        now = time.perf_counter()
        elapsed = now - t0

        # Stop condition: must run at least min_sec, and try to stop near target, hard stop at max_sec
        if elapsed >= max_s:
            break
        if elapsed >= target and elapsed >= min_s:
            break

        # Do one batch of samples
        for _ in range(batch):
            noisy = {}
            for k, x in values.items():
                noisy[k] = x * (1.0 + random.gauss(0.0, noise_sigma_rel))

            logit, rs = risk_logit(noisy)
            probs.append(_sigmoid(logit))
            used += 1

            # collect a small number of reasons for interpretability (avoid huge strings)
            if rs and len(reasons_pool) < 40:
                reasons_pool.extend(rs)

        # adaptive batch sizing (optional): if too slow, reduce batch so you can exit closer to target
        # Here we keep it simple and stable.

    probs.sort()
    prob_mean = (sum(probs) / len(probs)) if probs else 0.0
    prob_p05 = _percentile(probs, 0.05)
    prob_p95 = _percentile(probs, 0.95)

    alarm = (prob_mean >= alarm_prob_mean) and (prob_p05 >= alarm_prob_p05)

    # 4) Update rolling history AFTER computing (avoid leaking current into window stats)
    for k, x in values.items():
        ctx.history[k].append(x)

    elapsed_sec = time.perf_counter() - t0

    return {
        "alarm": alarm,
        "prob_mean": prob_mean,
        "prob_p05": prob_p05,
        "prob_p95": prob_p95,
        "elapsed_sec": elapsed_sec,
        "used_samples": used,
        "reasons": reasons_pool[:20] if reasons_pool else ["none"],
        "values": values,
    }
