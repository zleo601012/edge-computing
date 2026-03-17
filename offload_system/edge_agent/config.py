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
    csv_dir: str
    slot_seconds: int
    upload_every: int

    # http timeouts
    http_timeout_s: float
    execute_timeout_s: float

    # loops
    peer_refresh_seconds: float
    uploader_check_seconds: float
    scheduler_tick_seconds: float
    estimate_trigger_second: float
    reuse_last_payload: bool

    @property
    def collector_upload_url(self) -> str:
        return self.collector_url.rstrip("/") + "/upload_batch"


def load_config() -> Config:
    reuse_last_payload_raw = _env_str("REUSE_LAST_PAYLOAD", "1").strip().lower()
    reuse_last_payload = reuse_last_payload_raw in {"1", "true", "yes", "on"}

    return Config(
        node_id=_env_str("NODE_ID", "node-unknown"),
        node_type=_env_str("NODE_TYPE", "pi").lower(),
        # Default to k8s service DNS names (can still override via EST_URL/DET_URL/FINE_URL).
        est_url=_env_str("EST_URL", "http://threshold-service:8000/ingest"),
        det_url=_env_str("DET_URL", "http://svc-detect:8001/detect/eval"),
        fine_url=_env_str("FINE_URL", "http://suc-fine-detect:8002/fine/eval"),
        peers=_env_list("PEERS", ""),
        collector_url=_env_str("COLLECTOR_URL", "http://127.0.0.1:9000"),
        db_path=_env_str("DB_PATH", "./edge_agent.db"),
        csv_dir=_env_str("CSV_DIR", ""),
        slot_seconds=_env_int("SLOT_SECONDS", 5),
        upload_every=_env_int("UPLOAD_EVERY", 10),
        http_timeout_s=_env_float("HTTP_TIMEOUT", 1.0),
        execute_timeout_s=_env_float("EXECUTE_TIMEOUT", 1.0),
        peer_refresh_seconds=_env_float("PEER_REFRESH_SECONDS", 2.0),
        uploader_check_seconds=_env_float("UPLOADER_CHECK_SECONDS", 2.0),
        scheduler_tick_seconds=_env_float("SCHEDULER_TICK_SECONDS", 0.25),
        estimate_trigger_second=_env_float("ESTIMATE_TRIGGER_SECOND", 4.0),
        reuse_last_payload=reuse_last_payload,
    )
