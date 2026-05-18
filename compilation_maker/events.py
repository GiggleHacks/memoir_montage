"""Queue-based event bus shared between background workers and the GUI.

Events are simple tuples so the same channel works for CLI (printed) and GUI
(forwarded to JS). Shapes:

    ("log", message: str, level: str)            # level in {info, ok, warn, err}
    ("current", path: str, sub_text: str)
    ("counts", done: int, total: int, rate: float, eta: str)
    ("stats", cpu: float, ram: float, gpu: float|None, vram: float|None)
    ("phase", name: str)                         # idle | indexing | compiling | concat
    ("analysis", path: str, results: dict)       # per-file analyzer outputs
    ("eligible", count: int)
    ("done", summary: dict)
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


Event = tuple[Any, ...]


@dataclass
class Control:
    stop: threading.Event
    pause: threading.Event

    @classmethod
    def new(cls) -> "Control":
        return cls(stop=threading.Event(), pause=threading.Event())

    def wait_if_paused(self) -> None:
        while self.pause.is_set() and not self.stop.is_set():
            time.sleep(0.1)


class EventBus:
    """Producer side. Workers push tuples; consumers drain via .drain() or .get()."""

    def __init__(self) -> None:
        self._q: queue.Queue[Event] = queue.Queue()

    def emit(self, *event: Any) -> None:
        self._q.put(tuple(event))

    def log(self, message: str, level: str = "info") -> None:
        self.emit("log", message, level)

    def get(self, timeout: float | None = None) -> Event | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> list[Event]:
        out: list[Event] = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                break
        return out


def format_eta(seconds: float) -> str:
    if seconds <= 0 or seconds != seconds or seconds == float("inf"):
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
