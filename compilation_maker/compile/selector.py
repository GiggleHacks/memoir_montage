"""Cache query + filter toggles -> list of eligible (path, duration, year) tuples."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ..index.cache import Cache
from .source_filter import classify as _classify_source


@dataclass
class Eligible:
    path: str
    duration: float
    created_year: int | None
    has_audio: bool = True
    mtime: float = 0.0  # file mtime from cache — chronological sort key


def _norm_root(root: str | Path) -> str:
    return str(Path(root).resolve())


def select(
    cache: Cache,
    root: str | Path,
    *,
    filters: dict,
    thresholds: dict,
    report: dict | None = None,
) -> list[Eligible]:
    """Return eligible files under `root` given the filter toggles.

    If `report` is provided, it is mutated in place with per-reason exclusion
    counts under `report["counts"]` and a sample of excluded paths under
    `report["samples"]` (capped at 5 per reason).
    """
    root_str = _norm_root(root)
    rows = cache.all_under(root_str)
    min_dur = float(filters.get("min_duration", 5.5))
    nsfw_mode = str(filters.get("nsfw_mode", "exclude"))
    # backwards compat: old flat-bool settings
    if "nsfw_exclude" in filters and "nsfw_mode" not in filters:
        nsfw_mode = "exclude" if bool(filters["nsfw_exclude"]) else "off"
    talk_req = bool(filters.get("talking_required", True))

    src_strict = bool(filters.get("source_allowlist_strict", True))
    excl_vert = bool(filters.get("exclude_vertical", True))
    excl_dl = bool(filters.get("exclude_downloads", True))
    excl_lowres = bool(filters.get("exclude_low_resolution", True))

    strict = float(thresholds.get("nsfw_strict", 0.7))
    soft_min = int(thresholds.get("nsfw_soft_min_frames", 3))
    speech_min = float(thresholds.get("speech_fraction_min", 0.1))
    min_short_side = int(thresholds.get("min_short_side", 720))

    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}

    def _reject(reason: str, path: str) -> None:
        counts[reason] = counts.get(reason, 0) + 1
        s = samples.setdefault(reason, [])
        if len(s) < 5:
            s.append(path)

    out: list[Eligible] = []
    for r in rows:
        if r["error"]:
            _reject("error", r["path"])
            continue
        allowed, src_reason = _classify_source(
            r["path"], r["width"], r["height"],
            exclude_downloads=excl_dl,
            exclude_vertical=excl_vert,
            exclude_low_resolution=excl_lowres,
            source_allowlist_strict=src_strict,
            min_short_side=min_short_side,
        )
        if not allowed:
            _reject(src_reason or "source", r["path"])
            continue
        duration = r["duration"] or 0.0
        if duration < min_dur:
            _reject("short_duration", r["path"])
            continue
        peak = r["nsfw_peak"] or 0.0
        sc = r["nsfw_soft_count"] or 0
        is_nsfw = peak >= strict or sc >= soft_min
        if nsfw_mode == "exclude" and is_nsfw:
            _reject("nsfw", r["path"])
            continue
        if nsfw_mode == "only" and not is_nsfw:
            _reject("not_nsfw", r["path"])
            continue
        if talk_req and (r["speech_fraction"] or 0.0) < speech_min:
            _reject("no_speech", r["path"])
            continue
        out.append(Eligible(
            path=r["path"],
            duration=duration,
            created_year=r["created_year"],
            has_audio=bool(r["has_audio"]),
            mtime=float(r["mtime"] or 0.0),
        ))
    if report is not None:
        report["counts"] = counts
        report["samples"] = samples
    return out


def eligible_count(cache: Cache, root: str | Path, *, filters: dict, thresholds: dict) -> int:
    return len(select(cache, root, filters=filters, thresholds=thresholds))


# --- compile constraints ---------------------------------------------------

@dataclass
class PoolStats:
    """Summary of clips eligible for compile at a given swap interval."""
    unique_clips:      int
    available_seconds: float
    longest_seconds:   float
    shortest_seconds:  float
    swap_seconds:      float

    def as_dict(self) -> dict:
        return asdict(self)


def pool_stats(
    cache: Cache,
    root: str | Path,
    *,
    filters: dict,
    thresholds: dict,
    swap_seconds: float,
    mute: bool = False,
    audio_mode: str = "",
) -> PoolStats:
    """Compute pool stats matching compiler.py's pool definition exactly.

    The compile pipeline keeps clips that pass user filters AND
        duration >= swap_seconds + 0.5  AND  (has_audio == True OR mute mode).
    """
    # Normalize: audio_mode takes precedence over legacy mute
    if audio_mode:
        need_audio = audio_mode != "mute"
    else:
        need_audio = not mute
    eligibles = select(cache, root, filters=filters, thresholds=thresholds)
    min_clip = float(swap_seconds) + 0.5
    if not need_audio:
        pool = [e for e in eligibles if e.duration >= min_clip]
    else:
        pool = [e for e in eligibles if e.duration >= min_clip and e.has_audio]
    if not pool:
        return PoolStats(
            unique_clips=0,
            available_seconds=0.0,
            longest_seconds=0.0,
            shortest_seconds=0.0,
            swap_seconds=float(swap_seconds),
        )
    durations = [e.duration for e in pool]
    return PoolStats(
        unique_clips=len(pool),
        available_seconds=sum(durations),
        longest_seconds=max(durations),
        shortest_seconds=min(durations),
        swap_seconds=float(swap_seconds),
    )


def compile_constraints(
    cache: Cache,
    root: str | Path,
    *,
    filters: dict,
    thresholds: dict,
    swap_seconds: float,
    mute: bool = False,
    audio_mode: str = "",
    grid_options: Iterable[int] = (3, 4, 5, 6, 7, 8, 9, 10),
) -> dict:
    """Bundle pool stats + grid feasibility + a recommended config for the modal."""
    stats = pool_stats(cache, root, filters=filters, thresholds=thresholds,
                       swap_seconds=swap_seconds, mute=mute, audio_mode=audio_mode)
    unique = stats.unique_clips
    available = stats.available_seconds
    swap = float(swap_seconds)

    grid_options = list(grid_options)
    max_grid = 0
    tooltips: dict[str, str] = {}
    for n in grid_options:
        cells = n * n
        if unique == 0:
            tooltips[str(n)] = "No indexed clips. Click INDEX first."
        elif cells > unique:
            tooltips[str(n)] = (
                f"{n}x{n} needs {cells} unique clips, you have {unique}."
            )
        else:
            max_grid = max(max_grid, n)

    recommended: dict = {}
    if unique > 0 and max_grid > 0 and swap > 0:
        rec_n = _pick_recommended_grid(grid_options, max_grid, unique)
        cells = rec_n * rec_n
        max_total_for_n = available / cells if cells > 0 else 0.0
        rec_total = _floor_to_multiple(max_total_for_n, swap)
        if rec_total < swap:
            rec_total = swap  # at least one segment
        recommended = {
            "grid": rec_n,
            "swap_seconds": swap,
            "total_seconds": float(rec_total),
        }

    return {
        **stats.as_dict(),
        "max_grid": max_grid,
        "recommended": recommended,
        "tooltips": tooltips,
    }


def _pick_recommended_grid(options: list[int], max_grid: int, unique: int) -> int:
    """Pick the biggest comfortable grid: max where cells <= unique // 2 if possible,
    else max_grid. Halving the pool gives diversity headroom for repeats across
    segments without immediately hitting the limit."""
    halved = unique // 2 if unique >= 4 else unique
    candidates = [n for n in options if n * n <= halved and n <= max_grid]
    if candidates:
        return max(candidates)
    return max_grid


def _floor_to_multiple(value: float, step: float) -> float:
    if step <= 0:
        return 0.0
    return (int(value // step)) * step


def _build_ramp_sequence(max_n: int, segments: int) -> list[int]:
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


def validate_compile_options(
    cache: Cache,
    root: str | Path,
    *,
    filters: dict,
    thresholds: dict,
    grid: int,
    total_seconds: float,
    swap_seconds: float,
    no_repeat: bool = False,
    mute: bool = False,
    audio_mode: str = "",
    grid_ramp: bool = False,
) -> dict:
    """Validate a specific option combination. Returns a status + diagnostics dict."""
    stats = pool_stats(cache, root, filters=filters, thresholds=thresholds,
                       swap_seconds=swap_seconds, mute=mute, audio_mode=audio_mode)
    unique = stats.unique_clips
    available = stats.available_seconds

    cells = int(grid) * int(grid)
    segments = max(0, int(total_seconds // swap_seconds)) if swap_seconds > 0 else 0

    if grid_ramp:
        ramp_seq = _build_ramp_sequence(grid, segments)
        total_cells_needed = sum(seg_n * seg_n for seg_n in ramp_seq)
        max_seg_cells = max((seg_n * seg_n for seg_n in ramp_seq), default=0)
    else:
        total_cells_needed = segments * cells
        max_seg_cells = cells

    used_seconds = float(segments * swap_seconds) * (total_cells_needed / max(1, segments))
    max_total_for_grid = (available / max(1, max_seg_cells)) if max_seg_cells > 0 else 0.0

    reasons: list[str] = []
    warnings: list[str] = []

    if unique == 0:
        reasons.append("No indexed clips in this folder. Click INDEX first.")
        status = "impossible"
    elif max_seg_cells > unique:
        if grid_ramp:
            reasons.append(
                f"Grid ramp peak ({grid}×{grid} = {max_seg_cells} cells) "
                f"needs more unique clips than available ({unique})."
            )
        else:
            reasons.append(
                f"{grid}x{grid} needs {cells} unique clips, you have {unique}."
            )
        status = "impossible"
    elif segments < 1:
        reasons.append("Total length is shorter than one swap interval.")
        status = "impossible"
    elif no_repeat and total_cells_needed > unique:
        warnings.append(
            f"No-repeat needs {total_cells_needed} cells but only {unique} "
            f"unique clips. Some clips will repeat after exhausting pool."
        )
        status = "limited"
    elif used_seconds > available:
        ratio = used_seconds / available if available > 0 else 0
        warnings.append(
            f"{used_seconds:.0f}s of cell-time needed but pool only has "
            f"{available:.0f}s. Clips will repeat (~{ratio:.1f}× coverage)."
        )
        status = "limited"
    else:
        status = "ready"

    return {
        "status": status,
        "reasons": reasons,
        "warnings": warnings,
        "max_total_for_grid": max_total_for_grid,
        "used_seconds": used_seconds,
        "available_seconds": available,
        "unique_clips": unique,
        "segments": segments,
        "cells": cells,
        "total_cells_needed": total_cells_needed,
    }
