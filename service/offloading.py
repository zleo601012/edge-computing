# service/offloading.py
from __future__ import annotations

import json
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request
from typing import Dict, Any, Tuple, Optional, List

from service.water_detector import DetectionContext, compute_overlimit_task

# 服务器侧：为“不同来源节点”的任务分别维护ctx，避免把不同监测点数据混到一个滑窗里
_ctx_by_source: Dict[int, DetectionContext] = {}
_ctx_lock = threading.Lock()

_active_requests = 0
_active_lock = threading.Lock()


def _get_ctx_for_source(source_node_id: int, window_size: int = 120) -> DetectionContext:
    with _ctx_lock:
        if source_node_id not in _ctx_by_source:
            _ctx_by_source[source_node_id] = DetectionContext(window_size=window_size)
        return _ctx_by_source[source_node_id]


class _Handler(BaseHTTPRequestHandler):
    # 由 start_offload_server 注入
    LIMITS: Dict[str, float] = {}
    WINDOW_SIZE: int = 120

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # GET /status
        if self.path.startswith("/status"):
            with _active_lock:
                active = _active_requests
            self._send_json(200, {"active_requests": active, "time": time.time()})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        # POST /compute
        if not self.path.startswith("/compute"):
            self._send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            req = json.loads(body)

            source_node_id = int(req["source_node_id"])
            row = req["row"]  # dict
            # 可选：让发起方传 target/min/max（统一任务时长）
            target_sec = float(req.get("target_sec", 2.0))
            min_sec = float(req.get("min_sec", 1.0))
            max_sec = float(req.get("max_sec", 3.0))

            ctx = _get_ctx_for_source(source_node_id, window_size=self.WINDOW_SIZE)

            global _active_requests
            with _active_lock:
                _active_requests += 1

            try:
                res = compute_overlimit_task(
                    row=row,
                    ctx=ctx,
                    limits=self.LIMITS,
                    target_sec=target_sec,
                    min_sec=min_sec,
                    max_sec=max_sec,
                )
            finally:
                with _active_lock:
                    _active_requests -= 1

            self._send_json(200, {"ok": True, "result": res})

        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})


def start_offload_server(
    host: str,
    port: int,
    limits: Dict[str, float],
    *,
    window_size: int = 120,
) -> ThreadingHTTPServer:
    """
    在本节点启动卸载服务（后台线程）
    """
    _Handler.LIMITS = limits
    _Handler.WINDOW_SIZE = window_size

    httpd = ThreadingHTTPServer((host, port), _Handler)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def remote_compute(
    peer_host: str,
    peer_port: int,
    *,
    source_node_id: int,
    row: Dict[str, Any],
    timeout_sec: float = 5.0,
    target_sec: float = 2.0,
    min_sec: float = 1.0,
    max_sec: float = 3.0,
) -> Dict[str, Any]:
    """
    向对端发起卸载计算请求，返回 compute_overlimit_task 的结果 dict
    """
    url = f"http://{peer_host}:{peer_port}/compute"
    payload = {
        "source_node_id": source_node_id,
        "row": row,
        "target_sec": target_sec,
        "min_sec": min_sec,
        "max_sec": max_sec,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})

    with request.urlopen(req, timeout=timeout_sec) as resp:
        r = json.loads(resp.read().decode("utf-8"))

    if not r.get("ok", False):
        raise RuntimeError(r.get("error", "remote error"))
    return r["result"]


def get_peer_status(peer_host: str, peer_port: int, timeout_sec: float = 2.0) -> Dict[str, Any]:
    url = f"http://{peer_host}:{peer_port}/status"
    with request.urlopen(url, timeout=timeout_sec) as resp:
        return json.loads(resp.read().decode("utf-8"))
