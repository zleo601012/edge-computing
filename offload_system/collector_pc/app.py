from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiosqlite
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(title="Collector-PC")


def _env(name: str, default: str) -> str:
    import os
    v = os.getenv(name)
    return default if v is None or v == "" else v


DB_PATH = _env("COLLECTOR_DB_PATH", "./collector_pc.db")


class BatchReq(BaseModel):
    batch_id: str
    sent_ts: float
    node_id: str
    node_type: str
    slots: List[int]
    baseline: List[Dict[str, Any]] = []
    detect: List[Dict[str, Any]] = []
    fine: List[Dict[str, Any]] = []


@dataclass
class CollectorDB:
    db_path: str
    db: Optional[aiosqlite.Connection] = None

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
            CREATE TABLE IF NOT EXISTS upload_batches (
              batch_id TEXT PRIMARY KEY,
              sent_ts REAL NOT NULL,
              received_ts REAL NOT NULL,
              node_id TEXT NOT NULL,
              node_type TEXT NOT NULL,
              slots_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS baseline_all (
              node_id TEXT NOT NULL,
              slot INTEGER NOT NULL,
              trace_id TEXT NOT NULL,
              created_ts REAL NOT NULL,
              payload_json TEXT NOT NULL,
              PRIMARY KEY(node_id, slot)
            );

            CREATE TABLE IF NOT EXISTS detect_all (
              node_id TEXT NOT NULL,
              slot INTEGER NOT NULL,
              trace_id TEXT NOT NULL,
              created_ts REAL NOT NULL,
              abnormal INTEGER NOT NULL,
              payload_json TEXT NOT NULL,
              PRIMARY KEY(node_id, slot)
            );

            CREATE TABLE IF NOT EXISTS fine_all (
              node_id TEXT NOT NULL,
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
            CREATE INDEX IF NOT EXISTS idx_fine_all_node_slot ON fine_all(node_id, slot);
            """
        )
        await self.db.commit()

    async def insert_batch(self, b: BatchReq) -> None:
        assert self.db is not None
        # dedup by batch_id
        cur = await self.db.execute("SELECT 1 FROM upload_batches WHERE batch_id=?", (b.batch_id,))
        exists = await cur.fetchone()
        await cur.close()
        if exists:
            return

        await self.db.execute(
            "INSERT INTO upload_batches(batch_id, sent_ts, received_ts, node_id, node_type, slots_json) VALUES(?,?,?,?,?,?)",
            (b.batch_id, float(b.sent_ts), time.time(), b.node_id, b.node_type, json.dumps(b.slots)),
        )

        # upsert baseline/detect
        for row in b.baseline:
            await self.db.execute(
                "INSERT OR REPLACE INTO baseline_all(node_id, slot, trace_id, created_ts, payload_json) VALUES(?,?,?,?,?)",
                (
                    b.node_id,
                    int(row["slot"]),
                    str(row.get("trace_id", "")),
                    float(row.get("created_ts", 0.0)),
                    json.dumps(row.get("payload", {}), ensure_ascii=False),
                ),
            )
        for row in b.detect:
            await self.db.execute(
                "INSERT OR REPLACE INTO detect_all(node_id, slot, trace_id, created_ts, abnormal, payload_json) VALUES(?,?,?,?,?,?)",
                (
                    b.node_id,
                    int(row["slot"]),
                    str(row.get("trace_id", "")),
                    float(row.get("created_ts", 0.0)),
                    int(row.get("abnormal", 0) or 0),
                    json.dumps(row.get("payload", {}), ensure_ascii=False),
                ),
            )
        for row in b.fine:
            await self.db.execute(
                "INSERT INTO fine_all(node_id, slot, trace_id, created_ts, offloaded, executed_on, origin, ok, duration_ms, payload_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    b.node_id,
                    int(row["slot"]),
                    str(row.get("trace_id", "")),
                    float(row.get("created_ts", 0.0)),
                    int(row.get("offloaded", 0) or 0),
                    str(row.get("executed_on", "")),
                    str(row.get("origin", "")),
                    int(row.get("ok", 0) or 0),
                    float(row.get("duration_ms", 0.0) or 0.0),
                    json.dumps(row.get("payload", {}), ensure_ascii=False),
                ),
            )

        await self.db.commit()


db = CollectorDB(DB_PATH)


@app.on_event("startup")
async def _startup() -> None:
    await db.open()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await db.close()


@app.post("/upload_batch")
async def upload_batch(req: BatchReq) -> Dict[str, Any]:
    if not req.batch_id or not req.node_id:
        raise HTTPException(status_code=400, detail="missing batch_id or node_id")
    await db.insert_batch(req)
    return {"ok": True, "received_ts": time.time(), "batch_id": req.batch_id, "slots": req.slots}


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "db_path": DB_PATH, "ts": time.time()}
