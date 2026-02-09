from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

import httpx

from .config import Config
from .state import PeerState, STATE


async def refresh_peers_loop(cfg: Config) -> None:
    """
    Periodically ping peers /health and record rtt + peer metrics.
    """
    if not cfg.peers:
        return

    async with httpx.AsyncClient(timeout=cfg.http_timeout_s) as client:
        while True:
            for peer in cfg.peers:
                t0 = time.perf_counter()
                ok = False
                data: Dict[str, Any] = {}
                err = ""
                try:
                    resp = await client.get(peer.rstrip("/") + "/health")
                    rtt_ms = (time.perf_counter() - t0) * 1000.0
                    resp.raise_for_status()
                    data = resp.json()
                    ok = True
                except Exception as e:
                    rtt_ms = (time.perf_counter() - t0) * 1000.0
                    err = repr(e)

                async with STATE.lock:
                    ps = STATE.peers.get(peer) or PeerState(url=peer)
                    ps.last_rtt_ms = rtt_ms
                    ps.last_seen_ts = time.time()
                    ps.ok = ok
                    if ok:
                        ps.node_id = str(data.get("node_id", ""))
                        ps.node_type = str(data.get("node_type", ""))
                        ps.avg_ms = dict(data.get("avg_ms", {}) or {})
                        ps.in_flight = int(data.get("in_flight", 0) or 0)
                        ps.queue_len = int(data.get("queue_len", 0) or 0)
                    STATE.peers[peer] = ps

            await asyncio.sleep(cfg.peer_refresh_seconds)
