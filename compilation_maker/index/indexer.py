"""Per-tree indexing orchestrator. Walks files, runs analyzers, writes to cache.

Emits events to a shared EventBus for either CLI printing or GUI forwarding.
Cooperative cancellation between videos via Control.stop; pauses honored between
videos as well.
"""
from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass
from pathlib import Path

from ..events import Control, EventBus, format_eta
from ..settings import DEFAULTS
from ..compile.source_filter import classify as _classify_source
from .cache import Cache
from .enumerate import iter_videos
from .probe import probe


@dataclass
class IndexSummary:
    scanned: int = 0
    indexed: int = 0
    cached: int = 0
    failed: int = 0
    deleted_stale: int = 0
    seconds: float = 0.0


def scan_tree(
    root: Path,
    bus: EventBus,
    control: Control,
    *,
    cache: Cache | None = None,
    settings: dict | None = None,
) -> IndexSummary:
    root = Path(root).resolve()
    settings = settings or DEFAULTS
    sample_count = int(settings.get("indexer", {}).get("sample_count", 8))
    trim_pct = float(settings.get("indexer", {}).get("trim_pct", 0.05))
    max_workers = int(settings.get("indexer", {}).get("max_workers", 4))
    thresholds = settings.get("thresholds", {})
    filters = settings.get("filters", {})
    nsfw_soft = float(thresholds.get("nsfw_soft", 0.5))
    nsfw_strict = float(thresholds.get("nsfw_strict", 0.70))
    nsfw_soft_min = int(thresholds.get("nsfw_soft_min_frames", 3))
    speech_min = float(thresholds.get("speech_fraction_min", 0.10))
    motion_min = float(thresholds.get("motion_score_min", 0.02))
    min_duration = float(filters.get("min_duration", 5.5))

    cache = cache or Cache()
    summary = IndexSummary()
    started = time.time()

    bus.emit("phase", "indexing")
    bus.log(f"Enumerating videos under {root} …", "info")
    files = list(iter_videos(root))
    total = len(files)
    bus.log(f"Found {total} videos. Starting scan.", "info")

    present: set[str] = set()
    times: list[float] = []

    # Separate cached from uncached
    uncached: list[tuple[Path, object]] = []
    for p in files:
        if control.stop.is_set():
            break
        path_str = str(p)
        present.add(path_str)
        try:
            st = p.stat()
        except OSError as e:
            bus.log(f"stat failed: {p}: {e}", "err")
            summary.failed += 1
            summary.scanned += 1
            _emit_progress(bus, summary, total, times)
            continue

        fresh = cache.get_fresh(path_str, st.st_size, st.st_mtime)
        if fresh is not None:
            summary.cached += 1
            summary.scanned += 1
            peak = float(fresh["nsfw_peak"] or 0.0)
            soft_count = int(fresh["nsfw_soft_count"] or 0)
            flagged = peak >= nsfw_strict or soft_count >= nsfw_soft_min
            w = int(fresh["width"] or 0) if fresh["width"] else None
            h = int(fresh["height"] or 0) if fresh["height"] else None
            bus.log(_format_scan_line(p.name, peak, soft_count, sample_count, flagged,
                                      cached=True, width=w, height=h),
                    "err" if flagged else "info")
            bus.emit("current", path_str, "cached")
            _emit_progress(bus, summary, total, times)
            continue

        uncached.append((p, st))

    if control.stop.is_set():
        summary.seconds = time.time() - started
        _emit_stopped_summary(bus, summary, cache, root, thresholds, speech_min, motion_min, min_duration)
        return summary

    # Process uncached videos in parallel
    effective_workers = max(1, max_workers)

    def _do_one(path: Path, st: object) -> dict:
        return _process_one_video(path, st, sample_count, trim_pct, nsfw_soft)

    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        future_map: dict[Future, tuple[Path, object]] = {}
        for p, st in uncached:
            if control.stop.is_set():
                break
            control.wait_if_paused()
            fut = pool.submit(_do_one, p, st)
            future_map[fut] = (p, st)

        stopped_early = False
        for fut in as_completed(future_map):
            if control.stop.is_set():
                for f in future_map:
                    f.cancel()
                stopped_early = True
                break

            p, st = future_map[fut]
            path_str = str(p)
            t0_video = time.time()
            try:
                row = fut.result()
                cache.upsert(row)
                summary.indexed += 1

                nsfw_flagged = (row["nsfw_peak"] or 0.0) >= nsfw_strict or (row["nsfw_soft_count"] or 0) >= nsfw_soft_min
                w = row.get("width")
                h = row.get("height")
                is_vertical = bool(w and h and h > w)
                is_lowres = bool(w and h and min(w, h) < 720)
                src_ok, src_reason = _classify_source(
                    path_str, w, h,
                    exclude_downloads=True, exclude_vertical=False,
                    exclude_low_resolution=False, source_allowlist_strict=False,
                    min_short_side=720,
                )
                passes = {
                    "nsfw": not nsfw_flagged,
                    "face": (row["face_max_count"] or 0) >= 1,
                    "talking": (row["speech_fraction"] or 0.0) >= speech_min,
                    "motion": (row["motion_score"] or 0.0) >= motion_min,
                    "duration": (row["duration"] or 0.0) >= min_duration,
                    "orientation": not is_vertical,
                    "resolution": not is_lowres,
                    "source": src_ok,
                }
                bus.emit("analysis", path_str, {
                    "folder": p.parent.name or str(p.parent),
                    "name": p.name,
                    "path": path_str,
                    "size_bytes": st.st_size,
                    "duration": row["duration"],
                    "width": w,
                    "height": h,
                    "nsfw_peak": row["nsfw_peak"],
                    "nsfw_soft_count": row["nsfw_soft_count"],
                    "nsfw_flagged": nsfw_flagged,
                    "is_vertical": is_vertical,
                    "is_lowres": is_lowres,
                    "face_count": row["face_max_count"],
                    "motion_score": row["motion_score"],
                    "speech_fraction": row["speech_fraction"],
                    "source_reason": src_reason,
                    "passes": passes,
                })
            except Exception as e:
                row = {
                    "path": path_str,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "duration": None, "has_audio": 0,
                    "width": None, "height": None, "created_year": None,
                    "nsfw_peak": None, "nsfw_soft_count": None,
                    "face_max_count": None, "motion_score": None,
                    "speech_fraction": None,
                    "error": f"{type(e).__name__}: {e}",
                }
                cache.upsert(row)
                summary.failed += 1
                bus.log(f"failed {p.name}: {row['error']}", "err")
                bus.log(traceback.format_exc(limit=2), "err")

            times.append(time.time() - t0_video)
            summary.scanned += 1
            _emit_progress(bus, summary, total, times)

    if stopped_early:
        summary.seconds = time.time() - started
        _emit_stopped_summary(bus, summary, cache, root, thresholds, speech_min, motion_min, min_duration)
        return summary

    summary.deleted_stale = cache.delete_missing(present)
    if summary.deleted_stale:
        bus.log(f"Pruned {summary.deleted_stale} missing entries from cache.", "info")
    bus.log(f"Scan complete. {summary.indexed} new, {summary.cached} cached, {summary.failed} failed.", "ok")

    summary.seconds = time.time() - started

    try:
        agg = cache.aggregate(
            str(root),
            nsfw_strict=nsfw_strict,
            nsfw_soft_min=nsfw_soft_min,
            speech_min=speech_min,
            motion_min=motion_min,
            min_duration=min_duration,
        )
    except Exception as e:
        bus.log(f"aggregate stats failed: {e}", "err")
        agg = {}

    bus.emit("phase", "idle")
    bus.emit("done", {
        "root": str(root),
        "scanned": summary.scanned,
        "indexed": summary.indexed,
        "cached": summary.cached,
        "failed": summary.failed,
        "deleted_stale": summary.deleted_stale,
        "seconds": summary.seconds,
        "stats": agg,
    })
    return summary


def _emit_stopped_summary(
    bus: EventBus,
    summary: IndexSummary,
    cache: Cache,
    root: Path,
    thresholds: dict,
    speech_min: float,
    motion_min: float,
    min_duration: float,
) -> None:
    """Emit a partial summary when the user stops indexing early."""
    indexed_so_far = summary.indexed + summary.cached
    bus.log(
        f"Stopped — {indexed_so_far} video{'' if indexed_so_far == 1 else 's'} indexed so far. "
        f"You can compile with what's available or resume indexing later.",
        "ok",
    )
    nsfw_strict = float(thresholds.get("nsfw_strict", 0.70))
    nsfw_soft_min = int(thresholds.get("nsfw_soft_min_frames", 3))
    try:
        agg = cache.aggregate(
            str(root),
            nsfw_strict=nsfw_strict,
            nsfw_soft_min=nsfw_soft_min,
            speech_min=speech_min,
            motion_min=motion_min,
            min_duration=min_duration,
        )
    except Exception:
        agg = {}
    bus.emit("phase", "idle")
    bus.emit("done", {
        "root": str(root),
        "scanned": summary.scanned,
        "indexed": summary.indexed,
        "cached": summary.cached,
        "failed": summary.failed,
        "deleted_stale": 0,
        "seconds": summary.seconds,
        "stats": agg,
        "stopped_early": True,
    })


def _process_one_video(
    path: Path, st: object, sample_count: int, trim_pct: float, nsfw_soft: float
) -> dict:
    """Analyze a single video. Runs in a worker thread."""
    from ..analyzers.frames import pick_timestamps, extract_many
    from ..analyzers.nsfw import get_model as get_nsfw_model, reduce_nsfw
    from ..analyzers.face import max_face_count
    from ..analyzers.motion import motion_score
    from ..analyzers.vad import get_model as get_vad_model

    row = {
        "path": str(path),
        "size": st.st_size,
        "mtime": st.st_mtime,
        "duration": None,
        "has_audio": 0,
        "width": None,
        "height": None,
        "created_year": None,
        "nsfw_peak": None,
        "nsfw_soft_count": None,
        "face_max_count": None,
        "motion_score": None,
        "speech_fraction": None,
        "error": None,
    }

    info = probe(path)
    row.update({
        "duration": info.get("duration"),
        "has_audio": int(bool(info.get("has_audio"))),
        "width": info.get("width"),
        "height": info.get("height"),
        "created_year": info.get("created_year"),
    })
    duration = row["duration"] or 0.0

    timestamps = pick_timestamps(duration, sample_count=sample_count, trim_pct=trim_pct)
    jpegs = extract_many(path, timestamps)

    nsfw_model = get_nsfw_model()
    scores = nsfw_model.score_batch(jpegs)
    nsfw_peak, nsfw_soft_count = reduce_nsfw(scores, soft_threshold=nsfw_soft)
    row["nsfw_peak"] = nsfw_peak
    row["nsfw_soft_count"] = nsfw_soft_count

    row["face_max_count"] = max_face_count(jpegs) if jpegs else 0
    row["motion_score"] = motion_score(jpegs) if len(jpegs) >= 2 else 0.0

    if row["has_audio"]:
        try:
            frac, _ = get_vad_model().speech_fraction(path)
            row["speech_fraction"] = frac
        except Exception:
            row["speech_fraction"] = 0.0
    else:
        row["speech_fraction"] = 0.0

    return row


def _format_scan_line(
    name: str,
    nsfw_peak: float,
    nsfw_soft_count: int,
    sample_count: int,
    flagged: bool,
    *,
    cached: bool = False,
    width: int | None = None,
    height: int | None = None,
) -> str:
    tags: list[str] = []
    if flagged:
        glyph = "✗"
        tags.append(f"🔞 NSFW (peak {nsfw_peak:.2f}, {nsfw_soft_count}/{sample_count})")
    else:
        glyph = "·"
    if width and height:
        if height > width:
            tags.append(f"📱 vertical ({width}×{height})")
        else:
            tags.append(f"{width}×{height}")
        if min(width, height) < 720:
            tags.append("⚠ low-res")
    if cached:
        tags.append("[cached]")
    suffix = " · ".join(tags) if tags else f"(peak {nsfw_peak:.2f})"
    return f"{glyph}  {name}  →  {suffix}"


def _emit_progress(bus: EventBus, summary: IndexSummary, total: int, times: list[float]) -> None:
    rate = 0.0
    eta = "--:--"
    if times:
        recent = times[-50:]
        avg = sum(recent) / len(recent)
        rate = 1.0 / avg if avg > 0 else 0.0
        remaining = max(0, total - summary.scanned)
        eta = format_eta(remaining * avg)
    bus.emit("counts", summary.scanned, total, rate, eta)
