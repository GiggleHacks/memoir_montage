"""Render one NxN collage segment via a single ffmpeg invocation."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from ..events import Control, EventBus
from .filtergraph import build_segment_filtergraph, find_font


_SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    _SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


def find_ffmpeg() -> Optional[str]:
    """Return path to ffmpeg binary, or None if not locatable."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        from shutil import which
        return which("ffmpeg")


def render_segment(
    *,
    seg_path: Path,
    picks: list[dict],
    n: int,
    cell_w: int,
    cell_h: int,
    fps: int,
    swap_seconds: int,
    border: bool,
    show_name: bool,
    show_year: bool,
    mute: bool = False,
    audio_mode: str = "all",
    active_audio_idx: int = -1,
    output_w: int = 0,
    output_h: int = 0,
    ffmpeg: str,
    control: Control,
    bus: EventBus,
    border_color: str = "cyan",
    font_file: Optional[str] = None,
) -> tuple[bool, str]:
    """Run ffmpeg to produce one seg_NNN.mp4. Returns (ok, error_message)."""
    cmd: list[str] = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]

    # Input-side seeks (-ss before -i) for fast keyframe seeks.
    for p in picks:
        cmd += [
            "-ss", f"{float(p.get('in', 0.0)):.3f}",
            "-t", str(swap_seconds),
            "-i", str(p["path"]),
        ]

    if font_file is None:
        font_file = find_font()

    # Normalize legacy mute param
    if mute and audio_mode == "all":
        audio_mode = "mute"
    want_audio = audio_mode != "mute"

    filtergraph = build_segment_filtergraph(
        n=n, cell_w=cell_w, cell_h=cell_h, fps=fps,
        border=border, show_name=show_name, show_year=show_year,
        picks=picks, font_file=font_file, border_color=border_color,
        audio_mode=audio_mode, active_audio_idx=active_audio_idx,
        output_w=output_w, output_h=output_h,
    )

    # Big grids (esp. grid ramp peaks) produce filtergraphs that blow past the
    # Windows ~32k command-line limit. For anything large, write it to a file
    # and use -filter_complex_script. The threshold is conservative — every
    # ffmpeg build that supports complex graphs also supports the _script form.
    if len(filtergraph) > 6000:
        graph_file = seg_path.with_suffix(".filter.txt")
        try:
            graph_file.write_text(filtergraph, encoding="utf-8")
        except OSError as e:
            return False, f"could not write filtergraph: {e}"
        cmd += ["-filter_complex_script", str(graph_file), "-map", "[v]"]
    else:
        graph_file = None
        cmd += ["-filter_complex", filtergraph, "-map", "[v]"]
    if want_audio:
        cmd += [
            "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(swap_seconds), "-r", str(fps),
            str(seg_path),
        ]
    else:
        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-an",
            "-t", str(swap_seconds), "-r", str(fps),
            str(seg_path),
        ]

    try:
        # We deliberately don't pipe stdout — segment encode can take ~5-30s
        # depending on grid size; we want it to finish atomically.
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=600,
            creationflags=_SUBPROCESS_FLAGS,
        )
    except subprocess.TimeoutExpired:
        return False, "ffmpeg timed out"
    except OSError as e:
        return False, f"OSError: {e}"
    finally:
        if graph_file is not None:
            try:
                graph_file.unlink()
            except OSError:
                pass

    if control.stop.is_set():
        # User cancelled; remove the partial file if it exists.
        try:
            if seg_path.exists():
                seg_path.unlink()
        except OSError:
            pass
        return False, "cancelled"

    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
        # Keep the last 800 chars so the GUI log can show enough context
        return False, stderr[-800:].strip()
    if not seg_path.exists() or seg_path.stat().st_size == 0:
        return False, "ffmpeg returned 0 but no output file produced"
    return True, ""
