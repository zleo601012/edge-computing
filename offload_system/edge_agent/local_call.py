from __future__ import annotations

import time
from datetime import datetime
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

    @staticmethod
    def _to_float(v: Any) -> Optional[float]:
        if isinstance(v, bool) or v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return None

    def _extract_values(self, payload: Dict[str, Any]) -> Dict[str, float]:
        raw = payload.get("values") if isinstance(payload.get("values"), dict) else payload
        values: Dict[str, float] = {}
        for k, v in raw.items():
            fv = self._to_float(v)
            if fv is None:
                continue
            values[str(k)] = fv

        # common aliases for wastewater metrics
        alias_pairs = {
            "COD_mgL": "COD",
            "TN_mgL": "TN",
            "NH3N_mgL": "Am",
            "BOD_mgL": "BOD",
            "nh3n": "Am",
            "cod": "COD",
            "tn": "TN",
            "bod": "BOD",
        }
        for src, dst in alias_pairs.items():
            if dst not in values and src in values:
                values[dst] = values[src]

        return values

    @staticmethod
    def _normalize_ts(v: Any) -> Optional[float]:
        """
        Convert optional ts field to float seconds when possible.

        svc_detect/suc_fine_detect expect numeric ts (Optional[float]).
        Replayed CSV payloads often carry ts as formatted strings, which would
        otherwise cause HTTP 422 validation errors.
        """
        fv = LocalCaller._to_float(v)
        if fv is not None:
            return fv
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"):
                try:
                    return float(datetime.strptime(s, fmt).timestamp())
                except ValueError:
                    continue
        return None

    async def call_estimate(self, slot: int, trace_id: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], float, str]:
        values = self._extract_values(payload)
        data = {
            "node_id": str(payload.get("node_id") or self.cfg.node_id),
            "ts": self._normalize_ts(payload.get("ts")) if payload.get("ts") is not None else float(slot),
            "ts": payload.get("ts", slot),
            "values": values,
        }
        return await self._post(self.cfg.est_url, data)

    async def call_detect(self, slot: int, trace_id: str, payload: Dict[str, Any], baseline: Optional[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any], float, str]:
        _ = baseline  # kept for compatibility with other detect implementations
        values = self._extract_values(payload)
        data = {
            "node_id": str(payload.get("node_id") or self.cfg.node_id),
            "slot_id": str(slot),
            "ts": self._normalize_ts(payload.get("ts")),
            "ts": payload.get("ts"),
            "values": values,
        }
        return await self._post(self.cfg.det_url, data)

    async def call_fine(self, slot: int, trace_id: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], float, str]:
        values = self._extract_values(payload)
        data = {
            "event_id": str(payload.get("event_id") or trace_id),
            "node_type": str(payload.get("node_type") or self.cfg.node_type),
            "slot_id": str(payload.get("slot_id") or slot),
            "ts": self._normalize_ts(payload.get("ts")),
            "ts": payload.get("ts"),
            "values": values,
            "exceed_ratio": payload.get("exceed_ratio") if isinstance(payload.get("exceed_ratio"), dict) else {},
        }
        return await self._post(self.cfg.fine_url, data)

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
