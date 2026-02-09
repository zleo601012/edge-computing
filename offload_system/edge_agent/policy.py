from __future__ import annotations

from typing import Optional

from .state import PeerState


def pick_target_for_fine(peers: dict[str, PeerState]) -> Optional[str]:
    """
    Rule-based policy (placeholder for RL later):
    Choose peer with minimal score = rtt + avg_fine + 30*in_flight + 10*queue_len

    The caller should ensure `peers` only contains eligible strong nodes (UP2 / Jetson).
    """
    best_url = None
    best_score = None

    for url, ps in peers.items():
        if not ps.ok:
            continue
        avg_fine = float(ps.avg_ms.get("fine", 0.0) or 0.0)
        score = float(ps.last_rtt_ms) + avg_fine + 30.0 * float(ps.in_flight) + 10.0 * float(ps.queue_len)
        if best_score is None or score < best_score:
            best_score = score
            best_url = url

    return best_url
