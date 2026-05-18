"""PyWebView window + JS<->Python bridge.

JS calls Python via `pywebview.api.<method>(...)` — methods on `Api`.
Python pushes events to JS via window.evaluate_js("window._cm.onEvent(...)").

Phase 2 hooks `Api.start_compile` to the real renderer. For now it logs a
"not implemented" event.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

import webview  # type: ignore

from . import __version__, telemetry
from .events import Control, EventBus
from .index.cache import Cache
from .index.indexer import scan_tree
from .compile.selector import eligible_count, select  # noqa: F401
from .settings import load as load_settings, save as save_settings, resolve_filters


WEB_DIR = Path(__file__).parent / "web"


def _safe_json(obj):
    """Make values JSON-safe before sending to JS (handle non-finite floats, etc.)."""
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_json(v) for v in obj]
    return obj


class Api:
    """Object exposed to JS. Method names become `pywebview.api.<name>`."""

    def __init__(self) -> None:
        self._window: Optional[webview.Window] = None
        self._bus = EventBus()
        self._control = Control.new()
        self._telemetry_control = Control.new()
        self._cache: Optional[Cache] = None
        self._worker: Optional[threading.Thread] = None
        self._forwarder: Optional[threading.Thread] = None
        self._phase = "idle"

    # --- lifecycle ---
    def attach(self, window: webview.Window) -> None:
        self._window = window
        self._cache = Cache()
        self._forwarder = threading.Thread(target=self._forward_loop, daemon=True, name="event-fwd")
        self._forwarder.start()
        telemetry.start(self._bus, self._telemetry_control)
        self._bus.log("memoir montage ready", "ok")
        self._push_initial_state()

    def _push_initial_state(self) -> None:
        s = load_settings()
        self._eval(f"window._cm.onSettings({json.dumps(_safe_json(s))})")

    # --- forwarder ---
    def _eval(self, code: str) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(code)
        except Exception:
            pass

    def _forward_loop(self) -> None:
        while True:
            ev = self._bus.get(timeout=0.5)
            if ev is None:
                continue
            payload = _safe_json(list(ev))
            self._eval(f"window._cm.onEvent({json.dumps(payload)})")
            if ev[0] == "phase":
                self._phase = ev[1]

    # --- JS API ---
    def app_version(self) -> str:
        return __version__

    def select_folder(self) -> Optional[str]:
        if self._window is None:
            return None
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return None
        folder = result[0] if isinstance(result, (list, tuple)) else result
        s = load_settings()
        s["last_folder"] = folder
        save_settings(s)
        self._bus.log(f"selected {folder}", "info")
        # Immediately compute eligible stats from current cache (might be 0 on first ever run)
        self._emit_stats(folder, s)
        return folder

    def save_settings(self, payload: dict) -> bool:
        try:
            current = load_settings()
            current.update(payload)
            save_settings(current)
            return True
        except Exception as e:
            self._bus.log(f"save settings failed: {e}", "err")
            return False

    def save_filters(self, filters: dict) -> int:
        s = load_settings()
        # Replace filters wholesale (rather than merge) so flipping from a custom
        # preset back to a named preset doesn't leave stale custom flags around.
        existing = s.get("filters", {})
        merged = {"preset": existing.get("preset", "strict"),
                  "nsfw_mode": existing.get("nsfw_mode", "exclude")}
        merged.update(filters or {})
        s["filters"] = merged
        save_settings(s)
        if s.get("last_folder"):
            return self._emit_stats(s["last_folder"], s)
        return 0

    def save_output_options(self, output: dict) -> bool:
        s = load_settings()
        s["output"] = {**s["output"], **output}
        save_settings(s)
        return True

    def start_index(self, folder: str) -> bool:
        if self._worker is not None and self._worker.is_alive():
            self._bus.log("already running", "warn")
            return False
        self._control = Control.new()
        s = load_settings()
        if folder:
            s["last_folder"] = folder
            save_settings(s)

        def _run() -> None:
            try:
                assert self._cache is not None
                scan_tree(Path(folder), self._bus, self._control, cache=self._cache, settings=s)
            except Exception as e:
                self._bus.log(f"index crashed: {e}", "err")
            finally:
                if s.get("last_folder"):
                    self._emit_stats(s["last_folder"], s)

        self._worker = threading.Thread(target=_run, daemon=True, name="indexer")
        self._worker.start()
        return True

    def cancel(self) -> bool:
        self._control.stop.set()
        self._bus.log("cancel requested", "warn")
        return True

    def start_compile(self, folder: str, options: dict) -> bool:
        if self._worker is not None and self._worker.is_alive():
            self._bus.log("already running", "warn")
            return False
        self._control = Control.new()
        s = load_settings()
        s["output"] = {**s.get("output", {}), **(options or {})}
        if folder:
            s["last_folder"] = folder
        save_settings(s)

        def _run() -> None:
            try:
                from .compile.compiler import run_compile
                assert self._cache is not None
                result = run_compile(Path(folder), s["output"], s, self._bus, self._control, cache=self._cache)
                self._maybe_open_output(result, s["output"])
            except Exception as e:
                import traceback
                self._bus.log(f"compile crashed: {e}", "err")
                self._bus.log(traceback.format_exc(limit=3), "err")
                self._bus.emit("phase", "idle")

        self._worker = threading.Thread(target=_run, daemon=True, name="compiler")
        self._worker.start()
        return True

    def compile_constraints(self, folder: str, swap_seconds: float, audio_mode: str = "all") -> dict:
        """Return pool stats, max_grid, recommended config, and per-grid tooltips."""
        if not folder or not self._cache:
            return {
                "unique_clips": 0, "available_seconds": 0.0,
                "longest_seconds": 0.0, "shortest_seconds": 0.0,
                "swap_seconds": float(swap_seconds or 5.0),
                "max_grid": 0, "recommended": {}, "tooltips": {},
            }
        from .compile.selector import compile_constraints as _cc
        s = load_settings()
        resolved = resolve_filters(s)
        try:
            return _cc(
                self._cache, folder,
                filters=resolved, thresholds=s["thresholds"],
                swap_seconds=float(swap_seconds or 5.0),
                audio_mode=str(audio_mode or "all"),
            )
        except Exception as e:
            self._bus.log(f"compile_constraints failed: {e}", "err")
            return {
                "unique_clips": 0, "available_seconds": 0.0,
                "longest_seconds": 0.0, "shortest_seconds": 0.0,
                "swap_seconds": float(swap_seconds or 5.0),
                "max_grid": 0, "recommended": {}, "tooltips": {},
            }

    def validate_compile_options(self, folder: str, options: dict) -> dict:
        """Run live validation for the modal's current state."""
        if not folder or not self._cache or not options:
            return {
                "status": "impossible",
                "reasons": ["No folder selected."],
                "warnings": [],
                "max_total_for_grid": 0.0,
                "used_seconds": 0.0,
                "available_seconds": 0.0,
                "unique_clips": 0,
                "segments": 0,
                "cells": 0,
            }
        from .compile.selector import validate_compile_options as _v
        s = load_settings()
        resolved = resolve_filters(s)
        try:
            return _v(
                self._cache, folder,
                filters=resolved, thresholds=s["thresholds"],
                grid=int(options.get("grid") or 3),
                total_seconds=float(options.get("total_seconds", 120)),
                swap_seconds=float(options.get("swap_seconds", 5)),
                no_repeat=bool(options.get("no_repeat", False)),
                audio_mode=str(options.get("audio_mode", "all")),
                grid_ramp=bool(options.get("grid_ramp", False)),
            )
        except Exception as e:
            self._bus.log(f"validate_compile_options failed: {e}", "err")
            return {
                "status": "impossible",
                "reasons": [str(e)],
                "warnings": [],
                "max_total_for_grid": 0.0,
                "used_seconds": 0.0,
                "available_seconds": 0.0,
                "unique_clips": 0,
                "segments": 0,
                "cells": 0,
            }

    def duration_breakdown(self, folder: str) -> dict:
        """Return per-folder duration stats so the UI can advise the user on min_duration.

        Shape: {indexed: int, durations: list[float], longest: float, total: float}
        Empty list / zeros if nothing indexed.
        """
        if not folder or not self._cache:
            return {"indexed": 0, "durations": [], "longest": 0.0, "total": 0.0}
        try:
            rows = self._cache.all_under(folder)
        except Exception:
            return {"indexed": 0, "durations": [], "longest": 0.0, "total": 0.0}
        durations: list[float] = []
        for r in rows:
            if r["error"]:
                continue
            d = r["duration"]
            if d is not None and d > 0:
                durations.append(float(d))
        return {
            "indexed": len(rows),
            "durations": durations,
            "longest": max(durations) if durations else 0.0,
            "total":   sum(durations),
        }

    def list_eligible(self, folder: str, limit: int = 25) -> list[dict]:
        s = load_settings()
        if not self._cache:
            return []
        rows = select(self._cache, folder, filters=s["filters"], thresholds=s["thresholds"])
        return [
            {"path": e.path, "duration": e.duration, "year": e.created_year}
            for e in rows[:limit]
        ]

    # --- internals ---
    def _maybe_open_output(self, result: dict, output_settings: dict) -> None:
        """If compile succeeded and auto_open is enabled, open the file in the OS default player."""
        if not isinstance(result, dict):
            return
        if result.get("error") or result.get("cancelled"):
            return
        output = result.get("output")
        if not output:
            return
        if not output_settings.get("auto_open", True):
            return
        try:
            import os, sys, subprocess
            if sys.platform == "win32":
                os.startfile(output)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", output])
            else:
                subprocess.Popen(["xdg-open", output])
            self._bus.log(f"Opened {output}", "ok")
        except Exception as e:
            self._bus.log(f"Could not auto-open: {e}", "warn")

    def _emit_stats(self, folder: str, settings: dict) -> int:
        """Emit the full aggregate (eligible count + totals + per-filter breakdown)."""
        if self._cache is None:
            return 0
        try:
            filters = resolve_filters(settings)
            thresholds = settings["thresholds"]
            agg = self._cache.aggregate(
                folder,
                nsfw_strict=float(thresholds.get("nsfw_strict", 0.70)),
                nsfw_soft_min=int(thresholds.get("nsfw_soft_min_frames", 3)),
                speech_min=float(thresholds.get("speech_fraction_min", 0.10)),
                motion_min=float(thresholds.get("motion_score_min", 0.02)),
                min_duration=float(filters.get("min_duration", 5.5)),
            )
            # eligible from aggregate is heuristic (no source-filter logic);
            # use the precise selector count for the headline number.
            n = eligible_count(self._cache, folder, filters=filters, thresholds=thresholds)
            agg["eligible"] = n
            # Total runtime of just the eligible clips:
            elig = select(self._cache, folder, filters=filters, thresholds=thresholds)
            agg["eligible_duration_seconds"] = sum(e.duration for e in elig)
        except Exception as e:
            self._bus.log(f"stats recount failed: {e}", "err")
            return 0
        self._bus.emit("stats_index", agg)
        # Backward-compat: also emit the bare eligible event so older JS still works.
        self._bus.emit("eligible", n)
        return n


def launch() -> None:
    from .compile.compiler import cleanup_orphaned_temps
    cleaned = cleanup_orphaned_temps()
    if cleaned:
        print(f"Cleaned {cleaned} orphaned compile temp dir(s).")

    api = Api()
    window = webview.create_window(
        title="Memoir Montage",
        url=str(WEB_DIR / "index.html"),
        js_api=api,
        width=1360,
        height=1000,
        min_size=(1000, 760),
        background_color="#07091c",
        text_select=True,
    )
    api._window = window  # set early so create_file_dialog works in `attach`

    def _on_loaded() -> None:
        # Brief delay so the JS bridge is ready
        time.sleep(0.15)
        api.attach(window)

    window.events.loaded += _on_loaded
    webview.start(debug=False)


if __name__ == "__main__":
    launch()
