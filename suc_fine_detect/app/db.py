import os, json, time, sqlite3
from typing import Any, Dict, Optional

DB_PATH = os.getenv("DB_PATH", "state.db")

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def ensure_fine_table():
    conn = connect()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS fine_events(
            event_id TEXT PRIMARY KEY,
            slot_id TEXT,
            pollution_type TEXT NOT NULL,
            severity_score REAL NOT NULL,
            confidence REAL NOT NULL,
            result_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fine_slot ON fine_events(slot_id);")
        conn.commit()
    finally:
        conn.close()

def save_fine(event_id: str, slot_id: Optional[str], pollution_type: str, severity_score: float,
              confidence: float, result: Dict[str, Any]) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO fine_events(event_id, slot_id, pollution_type, severity_score, confidence, result_json, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (event_id, slot_id, pollution_type, float(severity_score), float(confidence),
             json.dumps(result, ensure_ascii=False), time.time()),
        )
        conn.commit()
    finally:
        conn.close()

def read_fine(event_id: str) -> Optional[Dict[str, Any]]:
    conn = connect()
    try:
        row = conn.execute("SELECT result_json FROM fine_events WHERE event_id=? LIMIT 1", (event_id,)).fetchone()
        if not row:
            return None
        return json.loads(row["result_json"])
    finally:
        conn.close()
