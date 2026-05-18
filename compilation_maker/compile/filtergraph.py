"""ffmpeg filter_complex builder for one NxN collage segment.

Produces an xstack of N² scaled+cropped video inputs into a width×height canvas
and amix of N² audio inputs. Drawtext (filename / year) and drawbox (border)
overlays are added per-cell when enabled.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def layout_string(n: int, cell_w: int, cell_h: int) -> str:
    """xstack layout: 'x_y|x_y|…' for an NxN grid of cells."""
    positions: list[str] = []
    for row in range(n):
        for col in range(n):
            positions.append(f"{col * cell_w}_{row * cell_h}")
    return "|".join(positions)


def escape_drawtext(s: str) -> str:
    """Escape characters that confuse ffmpeg drawtext text= value.

    drawtext text is single-quoted by the caller; inside we must escape
    backslash, colon, and remove single quotes entirely (no clean escape).
    Brackets, commas and percent signs also need escaping.
    """
    out = s.replace("\\", "\\\\")
    for ch in [":", "'", "[", "]", ",", ";", "%"]:
        if ch == "'":
            out = out.replace(ch, "")
        else:
            out = out.replace(ch, "\\" + ch)
    return out


def escape_fontfile(path: str) -> str:
    """Windows paths in drawtext need forward slashes and escaped colons."""
    p = path.replace("\\", "/")
    # escape the drive colon
    p = p.replace(":", r"\:")
    return p


def per_cell_video_chain(
    i: int,
    cell_w: int,
    cell_h: int,
    fps: int,
    *,
    border: bool,
    border_color: str,
    show_name: bool,
    show_year: bool,
    name: str,
    year: Optional[int],
    font_file: Optional[str],
    solo_active: bool = False,
) -> str:
    chain = (
        f"[{i}:v]"
        f"scale={cell_w}:{cell_h}:force_original_aspect_ratio=increase,"
        f"crop={cell_w}:{cell_h},setsar=1,fps={fps},format=yuv420p"
    )

    if border:
        chain += (
            f",drawbox=x=0:y=0:w={cell_w}:h={cell_h}:"
            f"color={border_color}@0.55:t=2"
        )

    if solo_active:
        chain += (
            f",drawbox=x=0:y=0:w={cell_w}:h={cell_h}:"
            f"color=gold@0.85:t=4"
        )

    parts: list[str] = []
    if show_name and name:
        # truncate very long filenames so labels don't dominate small cells
        max_chars = max(8, cell_w // 9)
        label = name if len(name) <= max_chars else name[: max_chars - 1] + "…"
        parts.append(label)
    if show_year and year:
        parts.append(str(year))

    if parts and font_file:
        text = " · ".join(parts)
        font_size = max(10, min(18, cell_h // 22))
        chain += (
            f",drawtext=fontfile='{escape_fontfile(font_file)}'"
            f":text='{escape_drawtext(text)}'"
            f":x=6:y=h-th-6:fontsize={font_size}:fontcolor=white@0.7"
            f":shadowcolor=black@0.6:shadowx=1:shadowy=1"
            f":box=1:boxcolor=black@0.35:boxborderw=3"
        )

    chain += f"[v{i}]"
    return chain


def per_cell_audio_chain(i: int) -> str:
    return (
        f"[{i}:a]aresample=async=1:first_pts=0,"
        f"aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000,"
        f"apad"
        f"[a{i}]"
    )


def build_segment_filtergraph(
    *,
    n: int,
    cell_w: int,
    cell_h: int,
    fps: int,
    border: bool,
    show_name: bool,
    show_year: bool,
    picks: list[dict],
    font_file: Optional[str] = None,
    border_color: str = "cyan",
    mute: bool = False,
    audio_mode: str = "all",
    active_audio_idx: int = -1,
    output_w: int = 0,
    output_h: int = 0,
) -> str:
    """Return the full -filter_complex argument value for one segment.

    `picks` is a list of N² dicts, each with at least: name (str), year (int|None).
    Cells are tiled left-to-right, top-to-bottom in `picks` order.
    """
    # Normalize: legacy mute param → audio_mode
    if mute and audio_mode == "all":
        audio_mode = "mute"
    want_audio = audio_mode != "mute"

    n_inputs = n * n
    if len(picks) != n_inputs:
        raise ValueError(f"expected {n_inputs} picks, got {len(picks)}")

    chains: list[str] = []
    for i, p in enumerate(picks):
        is_solo = (audio_mode == "solo" and i == active_audio_idx)
        chains.append(per_cell_video_chain(
            i, cell_w, cell_h, fps,
            border=border, border_color=border_color,
            show_name=show_name, show_year=show_year,
            name=p.get("name", ""), year=p.get("year"),
            font_file=font_file,
            solo_active=is_solo,
        ))
        if audio_mode == "all":
            chains.append(per_cell_audio_chain(i))
        elif audio_mode == "solo" and i == active_audio_idx:
            chains.append(per_cell_audio_chain(i))

    actual_w = n * cell_w
    actual_h = n * cell_h
    need_pad = output_w > 0 and output_h > 0 and (actual_w != output_w or actual_h != output_h)

    if n_inputs == 1:
        if need_pad:
            chains.append(f"[v0]pad={output_w}:{output_h}:0:0:color=black[v]")
        else:
            chains.append("[v0]copy[v]")
        if want_audio:
            if audio_mode == "solo":
                chains.append(f"[a{active_audio_idx}]acopy[a]")
            else:
                chains.append("[a0]acopy[a]")
    else:
        v_inputs = "".join(f"[v{i}]" for i in range(n_inputs))
        if need_pad:
            chains.append(
                f"{v_inputs}xstack=inputs={n_inputs}:layout={layout_string(n, cell_w, cell_h)}[vraw]"
            )
            chains.append(f"[vraw]pad={output_w}:{output_h}:0:0:color=black[v]")
        else:
            chains.append(
                f"{v_inputs}xstack=inputs={n_inputs}:layout={layout_string(n, cell_w, cell_h)}[v]"
            )
        if audio_mode == "all":
            a_inputs = "".join(f"[a{i}]" for i in range(n_inputs))
            chains.append(
                f"{a_inputs}amix=inputs={n_inputs}:duration=longest:normalize=0[a]"
            )
        elif audio_mode == "solo":
            chains.append(f"[a{active_audio_idx}]acopy[a]")

    return ";".join(chains)


def find_font() -> Optional[str]:
    """Locate a usable TTF for drawtext. Returns None if nothing found."""
    candidates: list[str] = []
    if sys.platform == "win32":
        candidates = [
            r"C:\Windows\Fonts\consola.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Menlo.ttc",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None
