from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import Config, load_config
from .local_call import LocalCaller
from .peers import refresh_peers_loop
from .policy import pick_target_for_fine
from .slot import current_slot
from .state import STATE
from .storage import Storage
from .uploader import uploader_loop


cfg: Config = load_config()
app = FastAPI(title=f"EdgeAgent-{cfg.node_id}")
logger = logging.getLogger("edge_agent.scheduler")


class IngestReq(BaseModel):
    payload: Dict[str, Any]
    trace_id: str = Field(default_factory=lambda: str(int(time.time() * 1000)))
    event_time: Optional[float] = None


class ExecuteReq(BaseModel):
    stage: str
    slot: int
    payload: Dict[str, Any]
    trace_id: str
    origin: str


class ExecuteResp(BaseModel):
    ok: bool
    executed_on: str
    slot: int
    trace_id: str
    duration_ms: float
    result: Dict[str, Any]
    error: str = ""


@dataclass
class SlotContext:
    slot: int
    slot_offset_s: float
    now_ts: float
    payload: Optional[Dict[str, Any]]
    payload_source: str


PhaseHandler = Callable[[SlotContext], Awaitable[None]]


class SlotScheduler:
    PHASE_ORDER = ("slot_start", "slot_mid", "slot_end", "slot_finalize")

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.phase_hooks: Dict[str, List[PhaseHandler]] = {k: [] for k in self.PHASE_ORDER}

    def register_phase(self, phase: str, handler: PhaseHandler) -> None:
        if phase not in self.phase_hooks:
            raise ValueError(f"unknown phase: {phase}")
        self.phase_hooks[phase].append(handler)

    async def run(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("scheduler tick failed: %s", exc)
            await asyncio.sleep(max(0.05, self.cfg.scheduler_tick_seconds))

    async def _tick(self) -> None:
        now = time.time()
        slot = current_slot(now, self.cfg.slot_seconds)
        offset = now - float(slot * self.cfg.slot_seconds)
        payload, src = await _resolve_slot_payload(slot)

        async with STATE.lock:
            STATE.active_slot = slot
            STATE.slot_phase_done.setdefault(slot, {})

        await self._run_phase_once("slot_start", slot, offset, now, payload, src)
        await self._run_phase_once("slot_mid", slot, offset, now, payload, src)
        if offset >= self.cfg.estimate_trigger_second:
            await self._run_phase_once("slot_end", slot, offset, now, payload, src)
        if offset >= (self.cfg.slot_seconds - max(0.2, self.cfg.scheduler_tick_seconds)):
            await self._run_phase_once("slot_finalize", slot, offset, now, payload, src)

        await self._trim_state(slot)

    async def _run_phase_once(
        self,
        phase: str,
        slot: int,
        offset: float,
        now_ts: float,
        payload: Optional[Dict[str, Any]],
        payload_source: str,
    ) -> None:
        async with STATE.lock:
            slot_state = STATE.slot_phase_done.setdefault(slot, {})
            if slot_state.get(phase, False):
                return
            slot_state[phase] = True

        logger.info(
            "slot=%s offset=%.3fs phase=%s payload_source=%s hooks=%s",
            slot,
            offset,
            phase,
            payload_source,
            len(self.phase_hooks[phase]),
        )

        ctx = SlotContext(
            slot=slot,
            slot_offset_s=offset,
            now_ts=now_ts,
            payload=payload,
            payload_source=payload_source,
        )
        for hook in self.phase_hooks[phase]:
            await hook(ctx)

    async def _trim_state(self, active_slot: int) -> None:
        async with STATE.lock:
            for old in list(STATE.slot_payload_cache.keys()):
                if old < active_slot - 50:
                    STATE.slot_payload_cache.pop(old, None)
            for old in list(STATE.slot_phase_done.keys()):
                if old < active_slot - 50:
                    STATE.slot_phase_done.pop(old, None)


storage = Storage(cfg.db_path, csv_dir=cfg.csv_dir)
caller = LocalCaller(cfg)
scheduler = SlotScheduler(cfg)


@app.on_event("startup")
async def _startup() -> None:
    await storage.open()

    async with STATE.lock:
        for p in cfg.peers:
            if p not in STATE.peers:
                from .state import PeerState

                STATE.peers[p] = PeerState(url=p)

    scheduler.register_phase("slot_start", _phase_slot_start_detect)
    scheduler.register_phase("slot_end", _phase_slot_end_estimate)
    scheduler.register_phase("slot_finalize", _phase_slot_finalize_log)

    asyncio.create_task(refresh_peers_loop(cfg), name="refresh_peers_loop")
    asyncio.create_task(uploader_loop(cfg, storage), name="uploader_loop")
    asyncio.create_task(scheduler.run(), name="slot_scheduler")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await caller.aclose()
    await storage.close()


@app.post("/ingest")
async def ingest(req: IngestReq) -> Dict[str, Any]:
    et = float(req.event_time) if req.event_time is not None else time.time()
    s = current_slot(et, cfg.slot_seconds)
    payload = dict(req.payload)
    async with STATE.lock:
        STATE.slot_payload_cache[s] = payload
        STATE.latest_payload = payload
    logger.info("ingest slot=%s trace_id=%s", s, req.trace_id)
    return {"accepted": True, "slot": s, "trace_id": req.trace_id}


@app.post("/execute", response_model=ExecuteResp)
async def execute(req: ExecuteReq) -> ExecuteResp:
    if req.stage != "fine":
        raise HTTPException(status_code=400, detail="unsupported stage")
    async with STATE.lock:
        STATE.in_flight += 1
    t0 = time.perf_counter()
    ok, result, _dur_ms, err = await caller.call_fine(req.slot, req.trace_id, req.payload)
    duration_ms = (time.perf_counter() - t0) * 1000.0
    async with STATE.lock:
        STATE.in_flight -= 1
        STATE.ewma["fine"].update(duration_ms)

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


async def _resolve_slot_payload(slot: int) -> tuple[Optional[Dict[str, Any]], str]:
    async with STATE.lock:
        payload = STATE.slot_payload_cache.get(slot)
        if payload is not None:
            return dict(payload), "current"
        if cfg.reuse_last_payload and STATE.latest_payload is not None:
            return dict(STATE.latest_payload), "latest"
    return None, "none"


async def _phase_slot_start_detect(ctx: SlotContext) -> None:
    if ctx.payload is None:
        logger.warning("slot=%s phase=slot_start skip detect: no payload", ctx.slot)
        return
    trace_id = f"slot-start-{ctx.slot}"
    logger.info("slot=%s phase=slot_start microservice=detect source=%s", ctx.slot, ctx.payload_source)
    await _run_detect_and_maybe_fine(slot=ctx.slot, trace_id=trace_id, payload=ctx.payload)


async def _phase_slot_end_estimate(ctx: SlotContext) -> None:
    if ctx.payload is None:
        logger.warning("slot=%s phase=slot_end skip estimate: no payload", ctx.slot)
        return
    next_slot = ctx.slot + 1
    logger.info("slot=%s phase=slot_end microservice=estimate target_slot=%s source=%s", ctx.slot, next_slot, ctx.payload_source)
    await _run_estimate(slot=next_slot, payload=ctx.payload)
    STATE.upload_event.set()


async def _phase_slot_finalize_log(ctx: SlotContext) -> None:
    logger.info("slot=%s phase=slot_finalize offset=%.3fs", ctx.slot, ctx.slot_offset_s)


async def _run_estimate(slot: int, payload: Dict[str, Any]) -> None:
    async with STATE.lock:
        STATE.in_flight += 1
    t0 = time.perf_counter()
    ok, result, _dur_ms, err = await caller.call_estimate(slot, trace_id=f"est-{slot}", payload=payload)
    duration_ms = (time.perf_counter() - t0) * 1000.0
    async with STATE.lock:
        STATE.in_flight -= 1
        STATE.ewma["estimate"].update(duration_ms)

    await storage.upsert_baseline(slot=slot, trace_id=f"est-{slot}", payload=(result if ok else {"error": err, "result": result}))


async def _run_detect_and_maybe_fine(slot: int, trace_id: str, payload: Dict[str, Any]) -> None:
    baseline = await storage.get_baseline(slot)
    async with STATE.lock:
        STATE.in_flight += 1
    t0 = time.perf_counter()
    ok, result, _dur_ms, err = await caller.call_detect(slot, trace_id=trace_id, payload=payload, baseline=baseline)
    duration_ms = (time.perf_counter() - t0) * 1000.0
    async with STATE.lock:
        STATE.in_flight -= 1
        STATE.ewma["detect"].update(duration_ms)

    abnormal = False
    if ok:
        abnormal = bool(result.get("abnormal", result.get("any_exceed", False)))
    else:
        result = {"error": err, "result": result}

    await storage.upsert_detect(slot=slot, trace_id=trace_id, abnormal=abnormal, payload=result)

    if abnormal:
        logger.info("slot=%s phase=slot_start microservice=fine abnormal=true", slot)
        await _run_fine_with_offload(slot=slot, trace_id=trace_id, payload=payload)


async def _run_fine_with_offload(slot: int, trace_id: str, payload: Dict[str, Any]) -> None:
    async with STATE.lock:
        peers_snapshot = dict(STATE.peers)

    target = pick_target_for_fine(peers_snapshot)
    if target:
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
