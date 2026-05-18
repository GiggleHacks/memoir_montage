"""Top-level compile orchestrator: select pool → render segments → concat → cleanup.

Run via `run_compile(root, options, settings, bus, control, cache=...)`. Emits
the same event vocabulary the indexer uses (phase / current / counts / log /
done) so the GUI doesn't need a separate event channel.
"""
from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from datetime import datetime
from pathlib import Path

from ..events import Control, EventBus, format_eta
from ..index.cache import Cache
from ..paths import compile_tmp_dir, compile_tmp_root
from .concat import concat_segments
from .filtergraph import find_font
from .segment import find_ffmpeg, render_segment
from .selector import select


_SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    _SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

_RUNNING_MARKER = ".running"


def cleanup_orphaned_temps() -> int:
    """Remove compile temp dirs left behind by crashes. Returns count cleaned."""
    root = compile_tmp_root()
    cleaned = 0
    try:
        for entry in root.iterdir():
            if entry.is_dir() and entry.name.startswith("compilation_maker_"):
                marker = entry / _RUNNING_MARKER
                if marker.exists():
                    shutil.rmtree(entry, ignore_errors=True)
                    cleaned += 1
    except OSError:
        pass
    return cleaned


def _build_ramp_sequence(max_n: int, segments: int) -> list[int]:
    """Build a progressive grid sequence: 1, 1, 2, 2, 3, 3, ... up to max_n, then hold."""
    seq: list[int] = []
    n = 1
    repeat = 0
    for _ in range(segments):
        seq.append(n)
        repeat += 1
        if repeat >= 2 and n < max_n:
            n += 1
            repeat = 0
    return seq


def run_compile(
    root: Path,
    options: dict,
    settings: dict,
    bus: EventBus,
    control: Control,
    *,
    cache: Cache | None = None,
) -> dict:
    """Render the NxN collage. Returns a summary dict; emits events throughout."""
    root = Path(root).resolve()
    cache = cache or Cache()

    n = int(options.get("grid", 3))
    total_seconds = int(options.get("total_seconds", 120))
    swap_seconds = int(options.get("swap_seconds", 5))
    border = bool(options.get("border", True))
    show_name = bool(options.get("filename_label", True))
    show_year = bool(options.get("year_label", True))
    no_repeat = bool(options.get("no_repeat", False))
    audio_mode = str(options.get("audio_mode", "all"))
    if audio_mode not in ("all", "mute", "solo"):
        audio_mode = "all"
    # Legacy compat
    if options.get("mute") and audio_mode == "all":
        audio_mode = "mute"
    grid_ramp = bool(options.get("grid_ramp", False))
    order = str(options.get("order", "chronological")).lower()
    if order not in ("chronological", "random", "no_repeat"):
        order = "chronological"
    # Legacy: the old "no_repeat" checkbox maps onto order="no_repeat".
    if no_repeat and order == "chronological":
        order = "no_repeat"
    width, height = options.get("resolution", [1920, 1080])
    fps = int(options.get("fps", 30))
    compile_workers = int(options.get("compile_workers", 0))

    # Cap at 6: 7+ (49+ simultaneous decodes + xstack + amix) blows up ffmpeg
    # on Windows with "Generic error in an external library". Track it and lift
    # the cap once we have a safer multi-pass path.
    if n < 2 or n > 6:
        bus.log(f"Grid size {n} out of range (2-6).", "err")
        bus.emit("phase", "idle")
        return {"error": "bad_options"}

    if swap_seconds < 1 or total_seconds < swap_seconds:
        bus.log(
            f"Invalid options: n={n} swap={swap_seconds}s total={total_seconds}s",
            "err",
        )
        bus.emit("phase", "idle")
        return {"error": "bad_options"}

    segments = max(1, total_seconds // swap_seconds)

    # Build per-segment grid sizes
    if grid_ramp:
        n_per_seg = _build_ramp_sequence(n, segments)
    else:
        n_per_seg = [n] * segments

    cell_w = width // n
    cell_h = height // n

    bus.emit("phase", "compiling")
    if grid_ramp:
        bus.log(
            f"Compile starting: GRID RAMP 1→{n}×{n} · {segments} segments × {swap_seconds}s "
            f"= {segments * swap_seconds}s · {width}x{height} @ {fps}fps",
            "info",
        )
    else:
        bus.log(
            f"Compile starting: {n}x{n} grid · {segments} segments × {swap_seconds}s "
            f"= {segments * swap_seconds}s · {width}x{height} @ {fps}fps",
            "info",
        )

    # Output size estimate
    estimated_mb = (width * height * fps * (segments * swap_seconds) * 0.07) / 1_000_000
    if estimated_mb > 2048:
        bus.log(
            f"⚠ Estimated output: ~{estimated_mb / 1024:.1f} GB. "
            f"Consider reducing total length or grid size.",
            "warn",
        )
    elif estimated_mb > 100:
        bus.log(f"Estimated output: ~{estimated_mb:.0f} MB.", "info")

    # Gate: did this folder get indexed at all?
    raw_rows = cache.all_under(str(root))
    if not raw_rows:
        bus.log(
            f"No indexed videos under {root}. Click INDEX first, then COMPILE.",
            "err",
        )
        bus.emit("phase", "idle")
        return {"error": "not_indexed"}

    from ..settings import resolve_filters
    resolved_filters = resolve_filters(settings)

    filter_report: dict = {}
    pool = select(
        cache, root,
        filters=resolved_filters, thresholds=settings["thresholds"],
        report=filter_report,
    )
    counts = filter_report.get("counts") or {}
    source_reasons = ("not_in_allowlist", "vertical", "low_resolution",
                       "tiktok", "downloader", "tiktok_id", "uuid")
    source_total = sum(counts.get(k, 0) for k in source_reasons)
    if source_total:
        parts = [f"{counts[k]} {k}" for k in source_reasons if counts.get(k)]
        bus.log(f"Source filter skipped {source_total} clip(s): " + ", ".join(parts), "info")
    longest = max((e.duration for e in pool), default=0.0)
    pool = [e for e in pool if e.duration >= swap_seconds + 0.5]
    if audio_mode == "mute":
        bus.log("Mute mode: audio will be stripped from output.", "info")
    else:
        if audio_mode == "solo":
            bus.log("Solo audio mode: one clip plays at a time with highlight.", "info")
        audio_pool = [e for e in pool if e.has_audio]
        if audio_pool:
            if len(audio_pool) < len(pool):
                bus.log(
                    f"Dropping {len(pool) - len(audio_pool)} silent clip(s) — audio mode needs audio.",
                    "warn",
                )
            pool = audio_pool
    if not pool:
        if longest > 0 and longest < swap_seconds + 0.5:
            bus.log(
                f"All eligible clips are shorter than the swap interval ({swap_seconds}s). "
                f"Longest clip is {longest:.1f}s. Lower swap interval or loosen filters.",
                "err",
            )
        else:
            bus.log(
                f"{len(raw_rows)} clips indexed but none pass the active filters. "
                f"Loosen the filters or expand the folder.",
                "err",
            )
        bus.emit("phase", "idle")
        return {"error": "empty_pool"}

    max_cells_per_seg = max(seg_n * seg_n for seg_n in n_per_seg)
    cells_per_seg = n * n  # used for non-ramp mode estimates
    bus.log(f"Eligible pool: {len(pool)} videos (max {max_cells_per_seg} cells in one segment).", "info")
    if len(pool) < max_cells_per_seg:
        bus.log(
            f"Pool ({len(pool)}) < max cells per segment ({max_cells_per_seg}) — files will repeat within a segment.",
            "warn",
        )

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        bus.log("ffmpeg binary not found. Install imageio-ffmpeg or system ffmpeg.", "err")
        bus.emit("phase", "idle")
        return {"error": "no_ffmpeg"}

    font_file = find_font()
    if (show_name or show_year) and not font_file:
        bus.log("No TTF font found — name/year overlays disabled for this run.", "warn")
        show_name = False
        show_year = False

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_dir = compile_tmp_dir(run_id)
    # Write crash-recovery marker
    (tmp_dir / _RUNNING_MARKER).write_text(run_id, encoding="utf-8")
    bus.log(f"Temp dir: {tmp_dir}", "info")

    # Determine worker count
    if compile_workers <= 0:
        compile_workers = min(2, os.cpu_count() or 2)

    rng = random.Random()
    started = time.time()
    used_paths: set[str] = set()

    total_cells_needed = sum(seg_n * seg_n for seg_n in n_per_seg)

    # For chronological and no_repeat, *never* let a clip repeat. If the pool
    # can't fill the requested length, trim segments off the end so we use the
    # pool exactly once. (Random keeps the wrap behavior since it's random.)
    if order in ("chronological", "no_repeat") and total_cells_needed > len(pool):
        cumulative = 0
        new_n_per_seg: list[int] = []
        for seg_n in n_per_seg:
            cells = seg_n * seg_n
            if cumulative + cells > len(pool):
                break
            new_n_per_seg.append(seg_n)
            cumulative += cells
        if not new_n_per_seg:
            bus.log(
                f"Pool too small ({len(pool)} clip(s)) for one {n_per_seg[0]}×{n_per_seg[0]} segment. "
                f"Lower the grid size or loosen filters.",
                "err",
            )
            bus.emit("phase", "idle")
            return {"error": "pool_too_small"}
        dropped = len(n_per_seg) - len(new_n_per_seg)
        if dropped:
            bus.log(
                f"⚠ Pool ({len(pool)}) smaller than requested ({total_cells_needed} cells). "
                f"Trimmed {dropped} segment(s) so no clip repeats — output will be "
                f"{len(new_n_per_seg) * swap_seconds}s instead of {segments * swap_seconds}s.",
                "warn",
            )
            n_per_seg = new_n_per_seg
            segments = len(n_per_seg)
            total_cells_needed = cumulative

    if no_repeat:
        bus.log(f"No-repeat mode: {len(pool)} unique clips for {total_cells_needed} total cells.", "info")

    # --- Pre-compute all picks ---
    all_picks: list[list[dict]] = []

    if order == "chronological":
        bus.log("Order: chronological — oldest clips first, flowing to newest.", "info")
        # Sort the pool once by file mtime (fall back to year + path for stability).
        chrono = sorted(
            pool,
            key=lambda e: (e.mtime or 0.0, e.created_year or 0, e.path),
        )
        # total_cells_needed is guaranteed <= len(pool) by the trim above.
        deck = chrono[:total_cells_needed]
        # Walk the deck segment by segment so cell 0 of seg 0 is the earliest clip.
        idx = 0
        for k in range(segments):
            seg_cells = n_per_seg[k] * n_per_seg[k]
            picks_src = deck[idx:idx + seg_cells]
            idx += seg_cells

            picks: list[dict] = []
            for e in picks_src:
                max_in = max(0.0, e.duration - swap_seconds - 0.1)
                in_point = rng.uniform(0.0, max_in) if max_in > 0.5 else 0.0
                picks.append({
                    "path": e.path,
                    "in": in_point,
                    "name": Path(e.path).stem,
                    "year": e.created_year,
                })
            all_picks.append(picks)
    else:
        # no_repeat: shuffle once and walk through. After the trim above, the
        # deck is guaranteed long enough to fill every segment without wrapping.
        if order == "no_repeat":
            deck = list(pool)
            rng.shuffle(deck)
            deck_idx = 0

        for k in range(segments):
            seg_cells = n_per_seg[k] * n_per_seg[k]
            if order == "no_repeat":
                picks_src = deck[deck_idx:deck_idx + seg_cells]
                deck_idx += seg_cells
            elif len(pool) >= seg_cells:
                picks_src = rng.sample(pool, seg_cells)
            else:
                picks_src = rng.choices(pool, k=seg_cells)

            picks = []
            for e in picks_src:
                max_in = max(0.0, e.duration - swap_seconds - 0.1)
                in_point = rng.uniform(0.0, max_in) if max_in > 0.5 else 0.0
                picks.append({
                    "path": e.path,
                    "in": in_point,
                    "name": Path(e.path).stem,
                    "year": e.created_year,
                })
            all_picks.append(picks)

    # --- Emit initial ETA estimate based on grid complexity ---
    avg_cells = total_cells_needed / max(1, segments)
    estimated_per_seg = avg_cells * swap_seconds * 0.3
    initial_eta = format_eta(segments * estimated_per_seg / max(1, compile_workers))
    bus.emit("counts", 0, segments, 0.0, f"~{initial_eta}")

    try:
        result = _render_all_segments(
            tmp_dir=tmp_dir,
            all_picks=all_picks,
            segments=segments,
            n_per_seg=n_per_seg,
            width=width, height=height, fps=fps,
            swap_seconds=swap_seconds,
            border=border, show_name=show_name, show_year=show_year,
            audio_mode=audio_mode,
            ffmpeg=ffmpeg, font_file=font_file,
            compile_workers=compile_workers,
            control=control, bus=bus, started=started,
        )
        if result is not None:
            return result

        # ----- concat -----
        bus.emit("phase", "concat")
        bus.emit("current", "concatenating segments", f"{segments} → one mp4")
        bus.log("Concatenating segments (stream copy)…", "info")
        output_path = root / f"compilation_{run_id}.mp4"
        ok, err = concat_segments(tmp_dir, segments, output_path, ffmpeg, bus)
        if not ok:
            bus.log(f"✗ Concat failed: {err}", "err")
            bus.emit("phase", "idle")
            return {"error": "concat_failed", "msg": err}

        elapsed_total = time.time() - started
        bus.log(
            f"✓ Compile complete in {format_eta(elapsed_total)}  →  {output_path}",
            "ok",
        )
        bus.emit("phase", "idle")
        bus.emit("done", {
            "type": "compile",
            "output": str(output_path),
            "segments": segments,
            "grid": n,
            "swap_seconds": swap_seconds,
            "total_seconds": segments * swap_seconds,
            "seconds": elapsed_total,
        })
        return {"output": str(output_path), "seconds": elapsed_total}

    finally:
        # Remove crash marker and clean up temp dir
        marker = tmp_dir / _RUNNING_MARKER
        if marker.exists():
            try:
                marker.unlink()
            except OSError:
                pass
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _validate_segment(seg_path: Path, swap_seconds: int, ffmpeg: str) -> bool:
    """Check that an existing segment file is a valid MP4 with expected duration."""
    if not seg_path.exists():
        return False
    if seg_path.stat().st_size < 1024:
        return False
    try:
        ffprobe = ffmpeg.replace("ffmpeg", "ffprobe")
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(seg_path),
        ]
        r = subprocess.run(
            cmd, capture_output=True, timeout=10, creationflags=_SUBPROCESS_FLAGS,
        )
        if r.returncode != 0:
            return False
        dur = float(r.stdout.decode().strip())
        return abs(dur - swap_seconds) < 1.5
    except Exception:
        return False


def _render_all_segments(
    *,
    tmp_dir: Path,
    all_picks: list[list[dict]],
    segments: int,
    n_per_seg: list[int],
    width: int, height: int, fps: int,
    swap_seconds: int,
    border: bool, show_name: bool, show_year: bool,
    audio_mode: str = "all",
    ffmpeg: str, font_file: str | None,
    compile_workers: int,
    control: Control, bus: EventBus, started: float,
) -> dict | None:
    """Render segments in parallel. Returns an error dict on failure, None on success."""
    seg_times: list[float] = []
    done_count = 0

    def _render_one(k: int) -> tuple[int, float, bool, str]:
        seg_path = tmp_dir / f"seg_{k:03d}.mp4"
        seg_n = n_per_seg[k]
        seg_cell_w = width // seg_n
        seg_cell_h = height // seg_n

        # Validate existing segment before reusing
        if seg_path.exists():
            if _validate_segment(seg_path, swap_seconds, ffmpeg):
                return k, 0.0, True, ""
            else:
                try:
                    seg_path.unlink()
                except OSError:
                    pass

        # Solo mode: cycle active cell across segments
        seg_cells = seg_n * seg_n
        active_idx = k % seg_cells if audio_mode == "solo" else -1

        t0 = time.time()
        ok, err = render_segment(
            seg_path=seg_path,
            picks=all_picks[k],
            n=seg_n, cell_w=seg_cell_w, cell_h=seg_cell_h, fps=fps,
            swap_seconds=swap_seconds,
            border=border, show_name=show_name, show_year=show_year,
            audio_mode=audio_mode,
            active_audio_idx=active_idx,
            output_w=width, output_h=height,
            ffmpeg=ffmpeg, control=control, bus=bus, font_file=font_file,
        )
        elapsed = time.time() - t0
        return k, elapsed, ok, err

    with ThreadPoolExecutor(max_workers=compile_workers) as pool:
        futures: dict[Future, int] = {}
        for k in range(segments):
            if control.stop.is_set():
                break
            fut = pool.submit(_render_one, k)
            futures[fut] = k

        for fut in as_completed(futures):
            if control.stop.is_set():
                for f in futures:
                    f.cancel()
                bus.log("Cancel: stopping render.", "warn")
                bus.emit("phase", "idle")
                return {"cancelled": True, "completed_segments": done_count}

            k, elapsed, ok, err = fut.result()
            seg_times.append(elapsed)
            done_count += 1

            if not ok:
                if "cancelled" in err.lower():
                    for f in futures:
                        f.cancel()
                    bus.log(f"Segment {k + 1} cancelled.", "warn")
                    bus.emit("phase", "idle")
                    return {"cancelled": True, "completed_segments": done_count}
                bus.log(f"✗ Segment {k + 1} failed: {err}", "err")
                bus.emit("phase", "idle")
                return {"error": "segment_failed", "k": k, "msg": err}

            seg_n = n_per_seg[k]
            seg_cells = seg_n * seg_n
            if elapsed > 0:
                bus.log(f"·  segment {k + 1:03d}/{segments} ({seg_n}×{seg_n})  →  rendered in {elapsed:.1f}s", "info")
            else:
                bus.log(f"·  segment {k + 1}/{segments} ({seg_n}×{seg_n})  →  reusing valid render", "info")

            bus.emit("current", f"segment {done_count}/{segments}", f"{seg_cells} cells · {swap_seconds}s")
            bus.emit("phase_label", f"Compiling segment {done_count}/{segments}")
            _emit_compile_progress(bus, done_count, segments, seg_times, started)

    return None


def _emit_compile_progress(
    bus: EventBus,
    done: int,
    total: int,
    times: list[float],
    started: float,
) -> None:
    nonzero = [t for t in times if t > 0]
    rate = (1.0 / (sum(nonzero) / len(nonzero))) if nonzero else 0.0
    avg = sum(nonzero) / len(nonzero) if nonzero else 0.0
    remaining = max(0, total - done) * avg
    bus.emit("counts", done, total, rate, format_eta(remaining))
