#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from typing import Dict, Iterable, Optional

import httpx

CANONICAL_MAP = {
    "COD_mgL": "COD",
    "COD_mg_L": "COD",
    "NH3N_mgL": "NH3N",
    "NH3N_mg_L": "NH3N",
    "TN_mgL": "TN",
    "TN_mg_L": "TN",
    "TP_mgL": "TP",
    "TP_mg_L": "TP",
    "DO_mgL": "DO",
    "DO_mg_L": "DO",
    "EC_uScm": "EC",
    "EC_uS_cm": "EC",
    "TSS_mgL": "TSS",
    "TSS_mg_L": "TSS",
    "turbidity_NTU": "turbidity",
    "rain_intensity_mmph": "rain_intensity",
    "flow_m3s": "flow",
    "temp_C": "temp",
    "pH": "pH",
}


def parse_ts(raw: str) -> Optional[float]:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).timestamp()
        except ValueError:
            continue
    try:
        return float(raw)
    except ValueError:
        return None


def to_float(value: str) -> Optional[float]:
    if value is None:
        return None
    v = str(value).strip()
    if v == "" or v.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def normalize_values(row: Dict[str, str], extra_metrics: Iterable[str]) -> Dict[str, float]:
    values: Dict[str, float] = {}
    for raw_key, raw_val in row.items():
        if raw_key in CANONICAL_MAP or raw_key in extra_metrics:
            val = to_float(raw_val)
            if val is None:
                continue
            key = CANONICAL_MAP.get(raw_key, raw_key)
            values[key] = val
    return values


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay dataset rows into threshold + detect microservices.")
    ap.add_argument("--csv", required=True, help="Path to dataset CSV (e.g., dataset/node_1.csv)")
    ap.add_argument("--threshold-url", default="http://127.0.0.1:8000", help="Threshold service base URL")
    ap.add_argument("--detect-url", default="http://127.0.0.1:8001", help="Detect service base URL")
    ap.add_argument("--node-col", default="node_id", help="Node ID column name")
    ap.add_argument("--ts-col", default="ts", help="Timestamp column name")
    ap.add_argument("--slot-col", default="slot", help="Slot ID column name")
    ap.add_argument("--speed", type=float, default=0.0, help="Replay speed. 1=real-time, 10=10x faster, 0=no sleep")
    ap.add_argument("--max-rows", type=int, default=0, help="Limit rows (0=all)")
    ap.add_argument("--extra-metrics", default="", help="Comma-separated extra metrics to pass through")
    args = ap.parse_args()

    extra_metrics = [x.strip() for x in args.extra_metrics.split(",") if x.strip()]

    threshold_url = args.threshold_url.rstrip("/") + "/ingest"
    detect_url = args.detect_url.rstrip("/") + "/detect/eval"

    first_ts: Optional[float] = None
    prev_ts: Optional[float] = None

    with httpx.Client(timeout=10.0) as client:
        with open(args.csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                if args.max_rows and idx >= args.max_rows:
                    break

                node_id = str(row.get(args.node_col, "") or "").strip()
                if not node_id:
                    continue

                values = normalize_values(row, extra_metrics)
                if not values:
                    continue

                slot = row.get(args.slot_col)
                slot_id = str(slot) if slot is not None else None
                ts = parse_ts(str(row.get(args.ts_col, "") or ""))

                if ts is not None:
                    if first_ts is None:
                        first_ts = ts
                    if prev_ts is None:
                        prev_ts = ts
                    if args.speed and args.speed > 0:
                        dt = ts - prev_ts
                        if dt > 0:
                            time.sleep(dt / args.speed)
                    prev_ts = ts

                threshold_payload = {"node_id": node_id, "values": values}
                if slot_id is not None:
                    threshold_payload["ts"] = slot_id
                elif ts is not None:
                    threshold_payload["ts"] = ts

                client.post(threshold_url, json=threshold_payload)

                detect_payload = {
                    "node_id": node_id,
                    "slot_id": slot_id,
                    "ts": ts,
                    "values": values,
                }
                client.post(detect_url, json=detect_payload)


if __name__ == "__main__":
    main()
