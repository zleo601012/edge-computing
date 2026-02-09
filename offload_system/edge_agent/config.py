from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return default if v is None or v == "" else v


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_list(name: str, default_csv: str = "") -> List[str]:
    raw = _env_str(name, default_csv)
    items = []
    for x in raw.split(","):
        x = x.strip()
        if x:
            items.append(x)
    return items


@dataclass(frozen=True)
class Config:
    # identity
    node_id: str
    node_type: str  # pi / up2 / jetson

    # workflow endpoints (local microservices)
    est_url: str
    det_url: str
    fine_url: str

    # cluster / peers
    peers: List[str]  # strong-node Edge Agents, e.g. http://up2-1:9100
    collector_url: str  # PC collector upload endpoint base, e.g. http://pc:9000

    # storage / timing
    db_path: str
    slot_seconds: int
    upload_every: int

    # http timeouts
    http_timeout_s: float
    execute_timeout_s: float

    # loops
    peer_refresh_seconds: float
    uploader_check_seconds: float

    @property
    def collector_upload_url(self) -> str:
        return self.collector_url.rstrip("/") + "/upload_batch"


def load_config() -> Config:
    return Config(
        node_id=_env_str("NODE_ID", "node-unknown"),
        node_type=_env_str("NODE_TYPE", "pi").lower(),
        est_url=_env_str("EST_URL", "http://127.0.0.1:8000/estimate"),
        det_url=_env_str("DET_URL", "http://127.0.0.1:8001/detect"),
        fine_url=_env_str("FINE_URL", "http://127.0.0.1:8002/fine"),
        peers=_env_list("PEERS", ""),
        collector_url=_env_str("COLLECTOR_URL", "http://127.0.0.1:9000"),
        db_path=_env_str("DB_PATH", "./edge_agent.db"),
        slot_seconds=_env_int("SLOT_SECONDS", 300),
        upload_every=_env_int("UPLOAD_EVERY", 10),
        http_timeout_s=_env_float("HTTP_TIMEOUT", 10.0),
        execute_timeout_s=_env_float("EXECUTE_TIMEOUT", 15.0),
        peer_refresh_seconds=_env_float("PEER_REFRESH_SECONDS", 2.0),
        uploader_check_seconds=_env_float("UPLOADER_CHECK_SECONDS", 2.0),
    )
