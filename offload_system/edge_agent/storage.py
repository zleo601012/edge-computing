from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite


@dataclass(frozen=True)
class BaselineRow:
    slot: int
    trace_id: str
    created_ts: float
    payload_json: str  # raw result JSON from estimate microservice


@dataclass(frozen=True)
class DetectRow:
    slot: int
    trace_id: str
    created_ts: float
    abnormal: int
    payload_json: str  # raw result JSON from detect microservice


@dataclass(frozen=True)
class FineRow:
    slot: int
    trace_id: str
    created_ts: float
    offloaded: int
    executed_on: str
    origin: str
    ok: int
    duration_ms: float
    payload_json: str  # raw result JSON from fine microservice OR remote execute wrapper


class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

    async def open(self) -> None:
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute("PRAGMA journal_mode=WAL;")
        await self.db.execute("PRAGMA synchronous=NORMAL;")
        await self._init_schema()

    async def close(self) -> None:
        if self.db:
            await self.db.close()
            self.db = None

    async def _init_schema(self) -> None:
        assert self.db is not None
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS baseline (
              slot INTEGER PRIMARY KEY,
              trace_id TEXT NOT NULL,
              created_ts REAL NOT NULL,
              payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS detect_result (
              slot INTEGER PRIMARY KEY,
              trace_id TEXT NOT NULL,
              created_ts REAL NOT NULL,
              abnormal INTEGER NOT NULL,
              payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fine_result (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              slot INTEGER NOT NULL,
              trace_id TEXT NOT NULL,
              created_ts REAL NOT NULL,
              offloaded INTEGER NOT NULL,
              executed_on TEXT NOT NULL,
              origin TEXT NOT NULL,
              ok INTEGER NOT NULL,
              duration_ms REAL NOT NULL,
              payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fine_slot ON fine_result(slot);

            CREATE TABLE IF NOT EXISTS upload_mark (
              slot INTEGER PRIMARY KEY,
              batch_id TEXT NOT NULL,
              uploaded_ts REAL NOT NULL
            );
            """
        )
        await self.db.commit()

    # ---------- baseline ----------
    async def upsert_baseline(self, slot: int, trace_id: str, payload: Dict[str, Any]) -> None:
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO baseline(slot, trace_id, created_ts, payload_json) VALUES(?,?,?,?) "
            "ON CONFLICT(slot) DO UPDATE SET trace_id=excluded.trace_id, created_ts=excluded.created_ts, payload_json=excluded.payload_json",
            (slot, trace_id, time.time(), json.dumps(payload, ensure_ascii=False)),
        )
        await self.db.commit()

    async def get_baseline(self, slot: int) -> Optional[Dict[str, Any]]:
        assert self.db is not None
        cur = await self.db.execute("SELECT payload_json FROM baseline WHERE slot=?", (slot,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return {"raw": row[0]}

    async def list_baseline_slots_not_uploaded(self) -> List[int]:
        """
        Closed slots are those that have baseline. Upload marks are tracked per slot.
        """
        assert self.db is not None
        cur = await self.db.execute(
            """
            SELECT b.slot
            FROM baseline b
            LEFT JOIN upload_mark u ON b.slot = u.slot
            WHERE u.slot IS NULL
            ORDER BY b.slot ASC
            """
        )
        rows = await cur.fetchall()
        await cur.close()
        return [int(r[0]) for r in rows]

    # ---------- detect ----------
    async def upsert_detect(self, slot: int, trace_id: str, abnormal: bool, payload: Dict[str, Any]) -> None:
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO detect_result(slot, trace_id, created_ts, abnormal, payload_json) VALUES(?,?,?,?,?) "
            "ON CONFLICT(slot) DO UPDATE SET trace_id=excluded.trace_id, created_ts=excluded.created_ts, abnormal=excluded.abnormal, payload_json=excluded.payload_json",
            (slot, trace_id, time.time(), 1 if abnormal else 0, json.dumps(payload, ensure_ascii=False)),
        )
        await self.db.commit()

    async def fetch_detect_for_slots(self, slots: List[int]) -> List[DetectRow]:
        if not slots:
            return []
        assert self.db is not None
        q = ",".join(["?"] * len(slots))
        cur = await self.db.execute(f"SELECT slot, trace_id, created_ts, abnormal, payload_json FROM detect_result WHERE slot IN ({q}) ORDER BY slot", slots)
        rows = await cur.fetchall()
        await cur.close()
        return [DetectRow(int(a), str(b), float(c), int(d), str(e)) for (a, b, c, d, e) in rows]

    # ---------- fine ----------
    async def insert_fine(
        self,
        slot: int,
        trace_id: str,
        offloaded: bool,
        executed_on: str,
        origin: str,
        ok: bool,
        duration_ms: float,
        payload: Dict[str, Any],
    ) -> None:
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO fine_result(slot, trace_id, created_ts, offloaded, executed_on, origin, ok, duration_ms, payload_json) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                slot,
                trace_id,
                time.time(),
                1 if offloaded else 0,
                executed_on,
                origin,
                1 if ok else 0,
                float(duration_ms),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        await self.db.commit()

    async def fetch_fine_for_slots(self, slots: List[int]) -> List[FineRow]:
        if not slots:
            return []
        assert self.db is not None
        q = ",".join(["?"] * len(slots))
        cur = await self.db.execute(
            f"SELECT slot, trace_id, created_ts, offloaded, executed_on, origin, ok, duration_ms, payload_json "
            f"FROM fine_result WHERE slot IN ({q}) ORDER BY slot, id",
            slots,
        )
        rows = await cur.fetchall()
        await cur.close()
        return [FineRow(int(a), str(b), float(c), int(d), str(e), str(f), int(g), float(h), str(i)) for (a, b, c, d, e, f, g, h, i) in rows]

    # ---------- upload mark ----------
    async def mark_uploaded(self, slots: List[int], batch_id: str) -> None:
        if not slots:
            return
        assert self.db is not None
        ts = time.time()
        await self.db.executemany(
            "INSERT OR REPLACE INTO upload_mark(slot, batch_id, uploaded_ts) VALUES(?,?,?)",
            [(int(s), str(batch_id), ts) for s in slots],
        )
        await self.db.commit()

    async def export_batch(self, slots: List[int]) -> Dict[str, Any]:
        """
        Export records for given slots.
        """
        assert self.db is not None
        # baseline
        if slots:
            q = ",".join(["?"] * len(slots))
            cur = await self.db.execute(f"SELECT slot, trace_id, created_ts, payload_json FROM baseline WHERE slot IN ({q}) ORDER BY slot", slots)
            b_rows = await cur.fetchall()
            await cur.close()
        else:
            b_rows = []

        baselines = []
        for (slot, trace_id, created_ts, payload_json) in b_rows:
            baselines.append(
                {
                    "slot": int(slot),
                    "trace_id": str(trace_id),
                    "created_ts": float(created_ts),
                    "payload": json.loads(payload_json) if payload_json else None,
                }
            )

        detects = []
        for d in await self.fetch_detect_for_slots(slots):
            detects.append(
                {
                    "slot": d.slot,
                    "trace_id": d.trace_id,
                    "created_ts": d.created_ts,
                    "abnormal": int(d.abnormal),
                    "payload": json.loads(d.payload_json) if d.payload_json else None,
                }
            )

        fines = []
        for f in await self.fetch_fine_for_slots(slots):
            fines.append(
                {
                    "slot": f.slot,
                    "trace_id": f.trace_id,
                    "created_ts": f.created_ts,
                    "offloaded": int(f.offloaded),
                    "executed_on": f.executed_on,
                    "origin": f.origin,
                    "ok": int(f.ok),
                    "duration_ms": float(f.duration_ms),
                    "payload": json.loads(f.payload_json) if f.payload_json else None,
                }
            )

        return {"slots": [int(s) for s in slots], "baseline": baselines, "detect": detects, "fine": fines}
