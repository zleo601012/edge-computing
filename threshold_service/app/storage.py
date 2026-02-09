# app/storage.py
import sqlite3, json, time
from typing import Optional, Dict, Any, Tuple

class ThresholdStore:
    def __init__(self, db_path: str = "thresholds.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.execute("""
        CREATE TABLE IF NOT EXISTS latest_threshold (
          node_id TEXT PRIMARY KEY,
          slot_id INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          thresholds_json TEXT NOT NULL
        )
        """)
        conn.commit()
        conn.close()

    def upsert_latest(self, node_id: str, slot_id: int, thresholds: Dict[str, Any]) -> None:
        conn = self._connect()
        conn.execute("""
        INSERT INTO latest_threshold(node_id, slot_id, updated_at, thresholds_json)
        VALUES(?,?,?,?)
        ON CONFLICT(node_id) DO UPDATE SET
          slot_id=excluded.slot_id,
          updated_at=excluded.updated_at,
          thresholds_json=excluded.thresholds_json
        """, (node_id, int(slot_id), int(time.time()), json.dumps(thresholds, ensure_ascii=False)))
        conn.commit()
        conn.close()

    def read_latest(self, node_id: str) -> Optional[Tuple[int, Dict[str, Any]]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT slot_id, thresholds_json FROM latest_threshold WHERE node_id=?",
            (node_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        slot_id, thr_json = row
        return int(slot_id), json.loads(thr_json)
