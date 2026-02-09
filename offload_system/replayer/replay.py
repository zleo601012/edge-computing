from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import httpx


def _parse_time(s: str) -> datetime:
    """
    Your dataset uses: '2023/7/1 0:00' (no seconds).
    """
    s = (s or "").strip()
    # try a couple formats
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # last resort: let datetime parse? (not available w/o dateutil) -> raise
    raise ValueError(f"Unsupported time format: {s!r}")


def _sanitize(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str):
        vv = v.strip()
        if vv == "" or vv.lower() in ("nan", "none", "null"):
            return None
        # keep as-is; numbers can be parsed by downstream services if needed
        return vv
    return v


def _load_agent_map(args: argparse.Namespace) -> Dict[str, str]:
    if args.agent_map_json:
        return json.loads(args.agent_map_json)
    if args.agent_map_file:
        with open(args.agent_map_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@dataclass
class RR:
    agents: Tuple[str, ...]
    i: int = 0

    def pick(self) -> str:
        if not self.agents:
            raise RuntimeError("No agents configured")
        url = self.agents[self.i % len(self.agents)]
        self.i += 1
        return url


async def main() -> None:
    ap = argparse.ArgumentParser(description="Replay one CSV dataset to multiple Edge Agents (/ingest).")
    ap.add_argument("--dataset", required=True, help="Path to CSV dataset.")
    ap.add_argument("--agent-map-json", default="", help='JSON mapping: {"ENT_1":"http://pi1:9100", ...}')
    ap.add_argument("--agent-map-file", default="", help="Path to JSON mapping file.")
    ap.add_argument("--default-agent", default="", help="Fallback agent URL if node_id not in map.")
    ap.add_argument("--agents", default="", help="Comma-separated agent URLs for round-robin fallback.")
    ap.add_argument("--time-col", default="xit", help="Timestamp column name.")
    ap.add_argument("--node-col", default="node_id", help="Origin node column name.")
    ap.add_argument("--relative-time", action="store_true", help="Use relative seconds since first row as event_time.")
    ap.add_argument("--speed", type=float, default=0.0, help="Replay speed. 1=real-time, 10=10x faster, 0=no sleep.")
    ap.add_argument("--slot-seconds", type=int, default=300, help="Slot seconds used by Edge Agents (for flush).")
    ap.add_argument("--concurrency", type=int, default=32, help="Max concurrent HTTP requests.")
    ap.add_argument("--ingest-path", default="/ingest", help="Ingest path on Edge Agent.")
    args = ap.parse_args()

    agent_map = _load_agent_map(args)
    rr_agents = tuple([x.strip() for x in (args.agents or "").split(",") if x.strip()])
    rr = RR(agents=rr_agents or tuple(agent_map.values()) or tuple([args.default_agent] if args.default_agent else []))

    sem = asyncio.Semaphore(max(1, args.concurrency))
    first_ts: Optional[datetime] = None
    prev_ts: Optional[datetime] = None
    agent_last_et: Dict[str, float] = {}

    async with httpx.AsyncClient(timeout=10.0) as client:
        async def send_one(agent_base: str, trace_id: str, event_time: float, payload: Dict[str, Any]) -> None:
            async with sem:
                url = agent_base.rstrip("/") + args.ingest_path
                try:
                    await client.post(url, json={"trace_id": trace_id, "event_time": event_time, "payload": payload})
                except Exception:
                    # best effort
                    pass

        tasks = []
        with open(args.dataset, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                node_id = str(row.get(args.node_col, "") or "")
                ts_raw = str(row.get(args.time_col, "") or "")
                try:
                    ts = _parse_time(ts_raw)
                except Exception:
                    continue

                if first_ts is None:
                    first_ts = ts
                if prev_ts is None:
                    prev_ts = ts

                # sleeping to simulate time
                if args.speed and args.speed > 0:
                    dt = (ts - prev_ts).total_seconds()
                    if dt > 0:
                        await asyncio.sleep(dt / args.speed)
                prev_ts = ts

                if args.relative_time and first_ts is not None:
                    event_time = (ts - first_ts).total_seconds()
                else:
                    event_time = ts.timestamp()

                payload = {k: _sanitize(v) for k, v in row.items()}

                if node_id in agent_map:
                    agent = agent_map[node_id]
                elif args.default_agent:
                    agent = args.default_agent
                else:
                    agent = rr.pick()

                agent_last_et[agent] = float(event_time)
                trace_id = f"{node_id}-{idx}"
                tasks.append(asyncio.create_task(send_one(agent, trace_id, float(event_time), payload)))

                # prevent memory blowup
                if len(tasks) >= args.concurrency * 5:
                    await asyncio.gather(*tasks)
                    tasks.clear()

        if tasks:
            await asyncio.gather(*tasks)


        # flush: advance one more slot to make agents close the last slot baseline
        flush_tasks = []
        for agent_base, last_et in agent_last_et.items():
            flush_tasks.append(asyncio.create_task(
                send_one(agent_base, trace_id=f"flush-{int(time.time()*1000)}", event_time=last_et + float(args.slot_seconds), payload={"__flush__": True})
            ))
        if flush_tasks:
            await asyncio.gather(*flush_tasks)

if __name__ == "__main__":
    asyncio.run(main())
