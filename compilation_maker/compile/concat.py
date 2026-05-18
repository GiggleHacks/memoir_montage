"""Concat-copy stage: stitch seg_*.mp4 into the final compilation."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..events import EventBus


_SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    _SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


def concat_segments(
    tmp_dir: Path,
    count: int,
    output_path: Path,
    ffmpeg: str,
    bus: EventBus,
) -> tuple[bool, str]:
    """Write concat.txt then stream-copy with ffmpeg's concat demuxer."""
    concat_txt = tmp_dir / "concat.txt"
    lines: list[str] = []
    for k in range(count):
        seg = tmp_dir / f"seg_{k:03d}.mp4"
        if not seg.exists():
            return False, f"missing segment {seg.name}"
        # concat demuxer wants forward slashes and single-quote escape on Windows
        path_str = str(seg).replace("\\", "/").replace("'", r"'\''")
        lines.append(f"file '{path_str}'")
    concat_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_txt),
        "-c", "copy",
        str(output_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=600,
            creationflags=_SUBPROCESS_FLAGS,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
        return False, stderr[-600:].strip()
    if not output_path.exists() or output_path.stat().st_size == 0:
        return False, "concat returned 0 but no output produced"
    return True, ""
