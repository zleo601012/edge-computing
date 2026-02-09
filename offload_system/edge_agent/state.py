from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class EWMA:
    alpha: float = 0.2
    value_ms: float = 0.0
    initialized: bool = False

    def update(self, sample_ms: float) -> float:
        if sample_ms < 0:
            sample_ms = 0.0
        if not self.initialized:
            self.value_ms = sample_ms
            self.initialized = True
        else:
            self.value_ms = self.alpha * sample_ms + (1.0 - self.alpha) * self.value_ms
        return self.value_ms


@dataclass
class PeerState:
    url: str
    last_rtt_ms: float = 9999.0
    last_seen_ts: float = 0.0
    node_id: str = ""
    node_type: str = ""
    avg_ms: Dict[str, float] = field(default_factory=dict)
    in_flight: int = 0
    queue_len: int = 0
    ok: bool = False


@dataclass
class State:
    # runtime
    started_ts: float = field(default_factory=lambda: time.time())
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ingest queue
    ingest_q: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2000))

    # slot tracking
    active_slot: Optional[int] = None
    slot_payload_cache: Dict[int, Dict[str, Any]] = field(default_factory=dict)  # one payload per slot
    detect_done_for_slot: Dict[int, bool] = field(default_factory=dict)

    # metrics
    ewma: Dict[str, EWMA] = field(default_factory=lambda: {
        "estimate": EWMA(),
        "detect": EWMA(),
        "fine": EWMA(),
        "fine_remote": EWMA(),
    })
    in_flight: int = 0

    # peer cache
    peers: Dict[str, PeerState] = field(default_factory=dict)  # key=url

    # upload trigger
    upload_event: asyncio.Event = field(default_factory=asyncio.Event)

    def queue_len(self) -> int:
        return self.ingest_q.qsize()


STATE = State()
