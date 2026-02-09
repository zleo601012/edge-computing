from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import httpx

from .config import Config


class LocalCaller:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = httpx.AsyncClient(timeout=cfg.http_timeout_s)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _post(self, url: str, data: Dict[str, Any], timeout_s: Optional[float] = None) -> Tuple[bool, Dict[str, Any], float, str]:
        t0 = time.perf_counter()
        try:
            resp = await self.client.post(url, json=data, timeout=timeout_s or self.cfg.http_timeout_s)
            dur_ms = (time.perf_counter() - t0) * 1000.0
            resp.raise_for_status()
            try:
                return True, resp.json(), dur_ms, ""
            except Exception:
                return True, {"raw": resp.text}, dur_ms, ""
        except Exception as e:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            return False, {}, dur_ms, repr(e)

    async def call_estimate(self, slot: int, trace_id: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], float, str]:
        return await self._post(self.cfg.est_url, {"slot": slot, "trace_id": trace_id, "payload": payload})

    async def call_detect(self, slot: int, trace_id: str, payload: Dict[str, Any], baseline: Optional[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any], float, str]:
        return await self._post(self.cfg.det_url, {"slot": slot, "trace_id": trace_id, "payload": payload, "baseline": baseline})

    async def call_fine(self, slot: int, trace_id: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], float, str]:
        return await self._post(self.cfg.fine_url, {"slot": slot, "trace_id": trace_id, "payload": payload})

    async def call_execute_remote(
        self,
        peer_url: str,
        stage: str,
        slot: int,
        trace_id: str,
        payload: Dict[str, Any],
        origin: str,
        timeout_s: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, Any], float, str]:
        url = peer_url.rstrip("/") + "/execute"
        return await self._post(
            url,
            {"stage": stage, "slot": slot, "trace_id": trace_id, "payload": payload, "origin": origin},
            timeout_s=timeout_s or self.cfg.execute_timeout_s,
        )
