from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from .config import Config
from .storage import Storage


async def _post_json(url: str, payload: Dict[str, Any], timeout_s: float) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        return True, ""
    except Exception as e:
        return False, repr(e)


async def uploader_loop(cfg: Config, storage: Storage) -> None:
    """
    Wait for upload_event, or periodically check whether there are enough closed slots to upload.
    """
    while True:
        # either event triggers (slot closed) or periodic wakeup
        try:
            await asyncio.wait_for(asyncio.shield(_wait_event(cfg)), timeout=cfg.uploader_check_seconds)
        except asyncio.TimeoutError:
            pass

        # check upload condition
        slots = await storage.list_baseline_slots_not_uploaded()
        if len(slots) < cfg.upload_every:
            continue

        # batch first N slots
        batch_slots = slots[: cfg.upload_every]
        batch_id = str(uuid.uuid4())

        batch = await storage.export_batch(batch_slots)
        batch_payload = {
            "batch_id": batch_id,
            "sent_ts": time.time(),
            "node_id": cfg.node_id,
            "node_type": cfg.node_type,
            **batch,
        }

        ok, err = await _post_json(cfg.collector_upload_url, batch_payload, timeout_s=cfg.execute_timeout_s)
        if ok:
            await storage.mark_uploaded(batch_slots, batch_id)
        else:
            # best effort: keep for retry on next loop
            # (you can add backoff here if needed)
            _ = err


async def _wait_event(cfg: Config) -> None:
    # imported lazily to avoid circular import
    from .state import STATE

    await STATE.upload_event.wait()
    STATE.upload_event.clear()
