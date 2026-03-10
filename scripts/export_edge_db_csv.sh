#!/usr/bin/env bash
set -euo pipefail

# Export edge-agent sqlite tables to CSV for easy inspection.
# Usage:
#   scripts/export_edge_db_csv.sh [DB_PATH] [OUT_DIR]
# Example:
#   scripts/export_edge_db_csv.sh ./edge_pi2.db ./csv_out

DB_PATH="${1:-${DB_PATH:-./edge_agent.db}}"
OUT_DIR="${2:-${OUT_DIR:-./csv_export}}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "ERROR: db file not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

python3 - "$DB_PATH" "$OUT_DIR" <<'PY'
import csv
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(sys.argv[1])
OUT_DIR = Path(sys.argv[2])

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

TABLES = [
    (
        "baseline",
        "SELECT slot, trace_id, created_ts, payload_json FROM baseline ORDER BY slot"
    ),
    (
        "detect_result",
        "SELECT slot, trace_id, created_ts, abnormal, payload_json FROM detect_result ORDER BY slot"
    ),
    (
        "fine_result",
        "SELECT id, slot, trace_id, created_ts, offloaded, executed_on, origin, ok, duration_ms, payload_json FROM fine_result ORDER BY id"
    ),
]

for name, sql in TABLES:
    out = OUT_DIR / f"{name}.csv"
    try:
      cur.execute(sql)
    except sqlite3.OperationalError:
      # table may not exist yet if no data/initialization on wrong db path
      with out.open("w", newline="", encoding="utf-8") as f:
          w = csv.writer(f)
          w.writerow(["note"])
          w.writerow([f"table '{name}' not found in {DB_PATH.name}"])
      print(f"[warn] {name}: table not found, wrote note csv -> {out}")
      continue

    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for row in rows:
            row = list(row)
            # pretty JSON field for readability in spreadsheets
            if cols and cols[-1] == "payload_json" and row[-1] is not None:
                try:
                    row[-1] = json.dumps(json.loads(row[-1]), ensure_ascii=False)
                except Exception:
                    pass
            w.writerow(row)
    print(f"[ok] {name}: {len(rows)} rows -> {out}")

conn.close()
print(f"[done] export complete. db={DB_PATH} out_dir={OUT_DIR}")
PY
