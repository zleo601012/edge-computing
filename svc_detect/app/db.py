import os, json, time, sqlite3
from typing import Any, Dict, Optional, Tuple, Union

DB_PATH = os.getenv("DB_PATH", "state.db")

ThresholdValue = Union[float, Tuple[float, float]]
ThresholdDict = Dict[str, ThresholdValue]

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # 允许“阈值写入程序”和“检测服务”并发更稳
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def ensure_events_table() -> None:
    conn = connect()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS events(
            event_id TEXT PRIMARY KEY,
            slot_id TEXT,
            level TEXT NOT NULL,
            any_exceed INTEGER NOT NULL,
            result_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_slot ON events(slot_id);")
        conn.commit()
    finally:
        conn.close()

def load_thresholds(slot_id: Optional[str]) -> Tuple[ThresholdDict, Dict[str, Any]]:
    """
    优先：取 valid_slot == slot_id 的阈值（最符合你的“上一时隙末估计 -> 下一时隙用”）
    回退：取最新一条阈值，并标 stale=True
    """
    conn = connect()
    try:
        row = None
        stale = False

        if slot_id:
            row = conn.execute(
                "SELECT valid_slot, thresholds_json, computed_at, version "
                "FROM thresholds WHERE valid_slot=? "
                "ORDER BY version DESC, computed_at DESC LIMIT 1",
                (slot_id,),
            ).fetchone()

        if row is None:
            stale = True
            row = conn.execute(
                "SELECT valid_slot, thresholds_json, computed_at, version "
                "FROM thresholds ORDER BY version DESC, computed_at DESC LIMIT 1"
            ).fetchone()

        if row is None:
            return {}, {"stale": True, "reason": "no_threshold_found"}

        thresholds = json.loads(row["thresholds_json"])
        meta = {
            "stale": stale,
            "valid_slot": row["valid_slot"],
            "computed_at": row["computed_at"],
            "version": row["version"],
        }
        return thresholds, meta
    finally:
        conn.close()

def save_event(event_id: str, slot_id: Optional[str], level: str, any_exceed: bool, result: Dict[str, Any]) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO events(event_id, slot_id, level, any_exceed, result_json, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (event_id, slot_id, level, 1 if any_exceed else 0, json.dumps(result, ensure_ascii=False), time.time()),
        )
        conn.commit()
    finally:
        conn.close()
