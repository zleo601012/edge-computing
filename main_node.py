#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Node main loop:
- every 5 seconds: read 1 row from CSV and compute detection result (1-3s)
- write results to output CSV
- designed to run on each Raspberry Pi separately

Run example on each Pi:
  python3 main_node.py --node-id 1 --csv data_part_1.csv --out results_part_1.csv
  python3 main_node.py --node-id 2 --csv data_part_2.csv --out results_part_2.csv
  python3 main_node.py --node-id 3 --csv data_part_3.csv --out results_part_3.csv
  python3 main_node.py --node-id 4 --csv data_part_4.csv --out results_part_4.csv
"""

from __future__ import annotations

import argparse
import csv
import time
import sys
from datetime import datetime

from service.water_detector import DetectionContext, compute_overlimit_task


SLOT_SECONDS = 5.0  # 5s一个时隙

# 你必须按自己的“超标标准”修改这里（先占位也能跑通系统）
LIMITS = {
    "Am": 25.0,
    "BOD": 300.0,
    "COD": 600.0,
    "TN": 50.0,
}


def run_node(node_id: int, csv_path: str, out_path: str, repeat: bool) -> None:
    ctx = DetectionContext(window_size=120)  # 10分钟滑窗（5s一条 => 120条）

    # 输出文件
    out_fp = open(out_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(
        out_fp,
        fieldnames=[
            "node_id",
            "slot_index",
            "wall_time",
            "alarm",
            "prob_mean",
            "prob_p05",
            "prob_p95",
            "elapsed_sec",
            "used_samples",
            "reasons",
            "Am",
            "BOD",
            "COD",
            "TN",
        ],
    )
    writer.writeheader()
    out_fp.flush()

    slot_index = 0
    t0 = time.monotonic()  # 用 monotonic 做时隙对齐更稳

    try:
        while True:
            # 打开CSV读一遍
            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    # --- 时隙对齐：保证每个 slot 尽量在 5s 边界开始 ---
                    slot_deadline = t0 + slot_index * SLOT_SECONDS
                    now = time.monotonic()
                    if now < slot_deadline:
                        time.sleep(slot_deadline - now)
                    else:
                        # 如果已经落后（比如计算太慢），就不sleep了，并给出提示
                        lag = now - slot_deadline
                        if lag > 0.2:  # 落后超过200ms才提示
                            print(f"[node={node_id}] WARNING: lagging behind schedule by {lag:.3f}s")

                    # --- 任务到达：读取一条数据 -> 调用计算函数（1~3s） ---
                    wall_time = datetime.now().isoformat(timespec="seconds")

                    res = compute_overlimit_task(
                        row=row,
                        ctx=ctx,
                        limits=LIMITS,
                        target_sec=2.0,  # 你想要的平均计算时间（会被约束在 min/max 内）
                        min_sec=1.0,
                        max_sec=3.0,
                        noise_sigma_rel=0.03,
                        alarm_prob_mean=0.90,
                        alarm_prob_p05=0.60,
                        seed=None,  # 想可复现实验可以给固定seed
                    )

                    # --- 输出与记录 ---
                    print(
                        f"[node={node_id} slot={slot_index:06d}] "
                        f"alarm={int(res['alarm'])} mean={res['prob_mean']:.3f} "
                        f"p05={res['prob_p05']:.3f} p95={res['prob_p95']:.3f} "
                        f"elapsed={res['elapsed_sec']:.3f}s samples={res['used_samples']} "
                        f"vals={res['values']} reasons={res['reasons']}"
                    )

                    writer.writerow(
                        {
                            "node_id": node_id,
                            "slot_index": slot_index,
                            "wall_time": wall_time,
                            "alarm": int(res["alarm"]),
                            "prob_mean": f"{res['prob_mean']:.6f}",
                            "prob_p05": f"{res['prob_p05']:.6f}",
                            "prob_p95": f"{res['prob_p95']:.6f}",
                            "elapsed_sec": f"{res['elapsed_sec']:.6f}",
                            "used_samples": res["used_samples"],
                            "reasons": "|".join(res["reasons"]) if isinstance(res["reasons"], list) else str(res["reasons"]),
                            "Am": row.get("Am", ""),
                            "BOD": row.get("BOD", ""),
                            "COD": row.get("COD", ""),
                            "TN": row.get("TN", ""),
                        }
                    )
                    out_fp.flush()

                    slot_index += 1

            if not repeat:
                print(f"[node={node_id}] Finished CSV. Exiting (repeat=False).")
                break

            print(f"[node={node_id}] Finished CSV. Restarting from beginning (repeat=True).")

    except KeyboardInterrupt:
        print(f"\n[node={node_id}] Interrupted by user. Exiting.")
    finally:
        out_fp.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node-id", type=int, required=True, choices=[1, 2, 3, 4], help="Node ID: 1..4")
    ap.add_argument("--csv", type=str, required=True, help="Path to node CSV, e.g., data_part_1.csv")
    ap.add_argument("--out", type=str, required=True, help="Output results CSV, e.g., results_part_1.csv")
    ap.add_argument("--repeat", action="store_true", help="Loop forever by repeating the CSV")
    args = ap.parse_args()

    # 基本检查
    missing = [k for k in ["Am", "BOD", "COD", "TN"] if k not in LIMITS]
    if missing:
        print("ERROR: LIMITS missing keys:", missing)
        sys.exit(1)

    run_node(node_id=args.node_id, csv_path=args.csv, out_path=args.out, repeat=args.repeat)


if __name__ == "__main__":
    main()
