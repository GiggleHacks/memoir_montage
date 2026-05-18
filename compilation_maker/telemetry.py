"""Polling thread: CPU, RAM, and optionally GPU/VRAM (NVIDIA only).

Pushes ("stats", cpu, ram, gpu, vram) events at ~2 Hz. gpu/vram are None on
non-NVIDIA systems; the GUI hides those bars accordingly.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from .events import Control, EventBus


def _try_nvml() -> Optional[object]:
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        if pynvml.nvmlDeviceGetCount() == 0:
            return None
        return pynvml
    except Exception:
        return None


def start(bus: EventBus, control: Control, *, interval: float = 0.5) -> threading.Thread:
    """Start a daemon polling thread. Returns the Thread object."""
    def _run() -> None:
        try:
            import psutil
        except ImportError:
            return
        nvml = _try_nvml()
        handle = None
        if nvml is not None:
            try:
                handle = nvml.nvmlDeviceGetHandleByIndex(0)
            except Exception:
                handle = None
        # psutil.cpu_percent needs a baseline tick
        psutil.cpu_percent(interval=None)
        while not control.stop.is_set():
            try:
                cpu = float(psutil.cpu_percent(interval=None))
                ram = float(psutil.virtual_memory().percent)
                gpu = None
                vram = None
                if handle is not None and nvml is not None:
                    try:
                        util = nvml.nvmlDeviceGetUtilizationRates(handle)
                        mem = nvml.nvmlDeviceGetMemoryInfo(handle)
                        gpu = float(util.gpu)
                        vram = float(mem.used) / float(mem.total) * 100.0
                    except Exception:
                        gpu = None
                        vram = None
                bus.emit("stats", cpu, ram, gpu, vram)
            except Exception:
                pass
            time.sleep(interval)

    t = threading.Thread(target=_run, daemon=True, name="telemetry")
    t.start()
    return t
