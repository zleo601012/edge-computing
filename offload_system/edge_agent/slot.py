from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotInfo:
    slot: int
    slot_seconds: int

    @property
    def start_time(self) -> float:
        return self.slot * self.slot_seconds

    @property
    def end_time(self) -> float:
        return (self.slot + 1) * self.slot_seconds


def current_slot(event_time: float, slot_seconds: int) -> int:
    """
    Slot index derived from event_time.

    - Real-time: event_time = time.time() (unix seconds) -> large slot ids, OK.
    - Offline replay: you can pass relative seconds (e.g. 0, 300, 600...) -> compact slot ids.
    """
    if event_time < 0:
        event_time = 0.0
    return int(event_time // slot_seconds)
