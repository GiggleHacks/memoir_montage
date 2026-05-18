"""Sample-frame extraction via ffmpeg. Returns JPEG bytes per timestamp."""
from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import imageio_ffmpeg
    _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    _FFMPEG = "ffmpeg"


_SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    _SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


def pick_timestamps(duration: float, sample_count: int = 8, trim_pct: float = 0.05) -> list[float]:
    if duration <= 0:
        return [0.0]
    if duration < 5.0:
        n = min(sample_count, 4)
        if n <= 1:
            return [duration / 2.0]
        return [duration * (i / (n - 1)) for i in range(n)]
    start = duration * trim_pct
    end = duration * (1.0 - trim_pct)
    if sample_count <= 1:
        return [(start + end) / 2.0]
    step = (end - start) / (sample_count - 1)
    return [start + i * step for i in range(sample_count)]


def extract_jpeg(path: Path, timestamp: float, max_side: int = 640) -> bytes | None:
    """Grab one frame at `timestamp` (seconds), return JPEG bytes. None on failure."""
    cmd = [
        _FFMPEG, "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, timestamp):.3f}",
        "-i", str(path),
        "-frames:v", "1",
        "-vf", f"scale='min({max_side},iw)':-2",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=_SUBPROCESS_FLAGS)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    return r.stdout


def extract_many(path: Path, timestamps: list[float], max_side: int = 640) -> list[bytes]:
    """Extract JPEGs for each timestamp in parallel; skips failures silently."""
    if not timestamps:
        return []
    workers = min(4, len(timestamps))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(extract_jpeg, path, ts, max_side) for ts in timestamps]
    results: list[bytes] = []
    for f in futures:
        jpeg = f.result()
        if jpeg:
            results.append(jpeg)
    return results
