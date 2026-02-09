from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import load_config, Config
from .slot import current_slot
from .state import STATE
from .storage import Storage
from .local_call import LocalCaller
from .peers import refresh_peers_loop
from .policy import pick_target_for_fine
from .uploader import uploader_loop


cfg: Config = load_config()
app = FastAPI(title=f"EdgeAgent-{cfg.node_id}")


class IngestReq(BaseModel):
    payload: Dict[str, Any]
    trace_id: str = Field(default_factory=lambda: str(int(time.time() * 1000)))
    event_time: Optional[float] = None  # offline replay can pass virtual time (seconds)


class ExecuteReq(BaseModel):
    stage: str  # e.g. "fine"
    slot: int
    payload: Dict[str, Any]
    trace_id: str
    origin: str  # origin node_id who requested the offload


class ExecuteResp(BaseModel):
    ok: bool
    executed_on: str
    slot: int
    trace_id: str
    duration_ms: float
    result: Dict[str, Any]
    error: str = ""


# runtime singletons
storage = Storage(cfg.db_path)
caller = LocalCaller(cfg)


@app.on_event("startup")
async def _startup() -> None:
    await storage.open()

    # init peers dict
    async with STATE.lock:
        for p in cfg.peers:
            if p not in STATE.peers:
                from .state import PeerState

                STATE.peers[p] = PeerState(url=p)

    # background tasks
    asyncio.create_task(refresh_peers_loop(cfg), name="refresh_peers_loop")
    asyncio.create_task(uploader_loop(cfg, storage), name="uploader_loop")
    asyncio.create_task(_worker_loop(), name="ingest_worker")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await caller.aclose()
    await storage.close()


@app.post("/ingest")
async def ingest(req: IngestReq) -> Dict[str, Any]:
    et = float(req.event_time) if req.event_time is not None else time.time()
    s = current_slot(et, cfg.slot_seconds)
    item = {"slot": s, "event_time": et, "trace_id": req.trace_id, "payload": req.payload}
    try:
        STATE.ingest_q.put_nowait(item)
    except asyncio.QueueFull:
        raise HTTPException(status_code=429, detail="ingest queue full")
    return {"accepted": True, "slot": s, "trace_id": req.trace_id, "queue_len": STATE.queue_len()}


@app.post("/execute", response_model=ExecuteResp)
async def execute(req: ExecuteReq) -> ExecuteResp:
    if req.stage != "fine":
        raise HTTPException(status_code=400, detail="unsupported stage")
    async with STATE.lock:
        STATE.in_flight += 1
    t0 = time.perf_counter()
    ok, result, dur_ms, err = await caller.call_fine(req.slot, req.trace_id, req.payload)
    duration_ms = (time.perf_counter() - t0) * 1000.0
    async with STATE.lock:
        STATE.in_flight -= 1
        STATE.ewma["fine"].update(duration_ms)

    # persist: this node executed for another origin
    await storage.insert_fine(
        slot=req.slot,
        trace_id=req.trace_id,
        offloaded=True,
        executed_on=cfg.node_id,
        origin=req.origin,
        ok=ok,
        duration_ms=duration_ms,
        payload={"fine_result": result, "error": err} if not ok else result,
    )

    return ExecuteResp(
        ok=ok,
        executed_on=cfg.node_id,
        slot=req.slot,
        trace_id=req.trace_id,
        duration_ms=duration_ms,
        result=result if ok else {"error": err},
        error=err,
    )


@app.get("/health")
async def health() -> Dict[str, Any]:
    async with STATE.lock:
        avg_ms = {k: float(v.value_ms) for k, v in STATE.ewma.items()}
        in_flight = int(STATE.in_flight)
        peers = {
            url: {
                "ok": ps.ok,
                "node_id": ps.node_id,
                "node_type": ps.node_type,
                "rtt_ms": ps.last_rtt_ms,
                "avg_ms": ps.avg_ms,
                "in_flight": ps.in_flight,
                "queue_len": ps.queue_len,
                "last_seen_ts": ps.last_seen_ts,
            }
            for url, ps in STATE.peers.items()
        }

    return {
        "node_id": cfg.node_id,
        "node_type": cfg.node_type,
        "started_ts": STATE.started_ts,
        "active_slot": STATE.active_slot,
        "queue_len": STATE.queue_len(),
        "in_flight": in_flight,
        "avg_ms": avg_ms,
        "peers": peers,
    }


# ---------------- worker loop ----------------

async def _worker_loop() -> None:
    """
    Single worker to keep slot transitions deterministic.
    """
    while True:
        item = await STATE.ingest_q.get()
        try:
            await _process_ingest_item(item)
        except Exception:
            # swallow to keep worker alive; add logs if needed
            pass
        finally:
            STATE.ingest_q.task_done()


async def _process_ingest_item(item: Dict[str, Any]) -> None:
    slot = int(item["slot"])
    trace_id = str(item["trace_id"])
    payload = dict(item["payload"])

    # special flush event: only advance slot and close previous ones
    if payload.get("__flush__") is True:
        await _maybe_advance_slot_and_close(slot)
        return

    # slot transition: close previous slots by running estimate
    await _maybe_advance_slot_and_close(slot)

    # cache one payload for this slot (last one wins)
    async with STATE.lock:
        STATE.slot_payload_cache[slot] = payload

    # run detect at "slot start" (first time we see this slot)
    first = False
    async with STATE.lock:
        if not STATE.detect_done_for_slot.get(slot, False):
            STATE.detect_done_for_slot[slot] = True
            first = True
    if first:
        await _run_detect_and_maybe_fine(slot=slot, trace_id=trace_id, payload=payload)


async def _maybe_advance_slot_and_close(new_slot: int) -> None:
    """
    If new_slot > active_slot, close all intermediate slots by running estimate on cached payloads.
    This makes baseline(t) available before detect(t+1).
    """
    async with STATE.lock:
        active = STATE.active_slot
    if active is None:
        async with STATE.lock:
            STATE.active_slot = new_slot
        return
    if new_slot <= active:
        return

    # close active .. new_slot-1
    for s in range(active, new_slot):
        async with STATE.lock:
            cached = STATE.slot_payload_cache.get(s)
        if cached is not None:
            await _run_estimate(slot=s, payload=cached)
            # trigger uploader check
            STATE.upload_event.set()

    async with STATE.lock:
        STATE.active_slot = new_slot
        # optional: keep only recent cache to save memory
        # we can delete slots < active-100 etc, but keep simple
        # NOTE: detect_done_for_slot can also be trimmed
        for old in list(STATE.slot_payload_cache.keys()):
            if old < new_slot - 50:
                STATE.slot_payload_cache.pop(old, None)
        for old in list(STATE.detect_done_for_slot.keys()):
            if old < new_slot - 50:
                STATE.detect_done_for_slot.pop(old, None)


async def _run_estimate(slot: int, payload: Dict[str, Any]) -> None:
    async with STATE.lock:
        STATE.in_flight += 1
    t0 = time.perf_counter()
    ok, result, dur_ms, err = await caller.call_estimate(slot, trace_id=f"est-{slot}", payload=payload)
    duration_ms = (time.perf_counter() - t0) * 1000.0
    async with STATE.lock:
        STATE.in_flight -= 1
        STATE.ewma["estimate"].update(duration_ms)

    # store baseline no matter ok (so downstream has something to read)
    await storage.upsert_baseline(slot=slot, trace_id=f"est-{slot}", payload=(result if ok else {"error": err, "result": result}))


async def _run_detect_and_maybe_fine(slot: int, trace_id: str, payload: Dict[str, Any]) -> None:
    baseline = await storage.get_baseline(slot - 1)
    async with STATE.lock:
        STATE.in_flight += 1
    t0 = time.perf_counter()
    ok, result, dur_ms, err = await caller.call_detect(slot, trace_id=trace_id, payload=payload, baseline=baseline)
    duration_ms = (time.perf_counter() - t0) * 1000.0
    async with STATE.lock:
        STATE.in_flight -= 1
        STATE.ewma["detect"].update(duration_ms)

    abnormal = False
    if ok:
        # convention: detect service returns {"abnormal": true/false, ...}
        abnormal = bool(result.get("abnormal", False))
    else:
        # if detect fails, mark abnormal=false but persist error
        result = {"error": err, "result": result}
        abnormal = False

    await storage.upsert_detect(slot=slot, trace_id=trace_id, abnormal=abnormal, payload=result)

    if abnormal:
        await _run_fine_with_offload(slot=slot, trace_id=trace_id, payload=payload)


async def _run_fine_with_offload(slot: int, trace_id: str, payload: Dict[str, Any]) -> None:
    # snapshot peers
    async with STATE.lock:
        peers_snapshot = dict(STATE.peers)

    target = pick_target_for_fine(peers_snapshot)
    if target:
        # try remote first
        async with STATE.lock:
            STATE.in_flight += 1
        t0 = time.perf_counter()
        ok, result, _, err = await caller.call_execute_remote(
            peer_url=target,
            stage="fine",
            slot=slot,
            trace_id=trace_id,
            payload=payload,
            origin=cfg.node_id,
        )
        duration_ms = (time.perf_counter() - t0) * 1000.0
        async with STATE.lock:
            STATE.in_flight -= 1
            STATE.ewma["fine_remote"].update(duration_ms)

        if ok:
            await storage.insert_fine(
                slot=slot,
                trace_id=trace_id,
                offloaded=True,
                executed_on=target,
                origin=cfg.node_id,
                ok=True,
                duration_ms=duration_ms,
                payload=result,
            )
            return

        # remote failed -> fall back local
        await storage.insert_fine(
            slot=slot,
            trace_id=trace_id,
            offloaded=True,
            executed_on=target,
            origin=cfg.node_id,
            ok=False,
            duration_ms=duration_ms,
            payload={"error": err, "result": result},
        )

    # local fine
    async with STATE.lock:
        STATE.in_flight += 1
    t0 = time.perf_counter()
    ok, result, _, err = await caller.call_fine(slot, trace_id=trace_id, payload=payload)
    duration_ms = (time.perf_counter() - t0) * 1000.0
    async with STATE.lock:
        STATE.in_flight -= 1
        STATE.ewma["fine"].update(duration_ms)

    await storage.insert_fine(
        slot=slot,
        trace_id=trace_id,
        offloaded=False,
        executed_on=cfg.node_id,
        origin=cfg.node_id,
        ok=ok,
        duration_ms=duration_ms,
        payload=(result if ok else {"error": err, "result": result}),
    )
