"""Duration & metadata probing.

Fast path: pure-Python ISO-BMFF (.mp4/.mov/.m4v) atom walker that reads only the
moov.mvhd box. Falls back to invoking ffmpeg/ffprobe for other containers.

Also extracts width/height/has_audio via ffprobe when needed.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    import imageio_ffmpeg
    _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    _FFMPEG = "ffmpeg"


# ffprobe is not bundled with imageio_ffmpeg's wheel, but it lives next to ffmpeg
# in most distributions. We fall back to parsing ffmpeg -i stderr if missing.
def _ffprobe_exe() -> str | None:
    candidate = Path(_FFMPEG).with_name("ffprobe" + (".exe" if sys.platform == "win32" else ""))
    if candidate.exists():
        return str(candidate)
    # try PATH
    from shutil import which
    return which("ffprobe")


_SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    _SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


# ---------- pure-python MP4/MOV duration ----------

_ISO_CONTAINERS = {b"moov", b"trak", b"mdia", b"edts", b"meta"}


def mp4_duration(path: Path) -> Optional[float]:
    """Return duration seconds, or None if this isn't ISO-BMFF / atom not found."""
    try:
        with open(path, "rb") as f:
            return _walk_for_mvhd(f, end=path.stat().st_size)
    except (OSError, struct.error):
        return None


def _walk_for_mvhd(f, end: int) -> Optional[float]:
    while f.tell() < end:
        header = f.read(8)
        if len(header) < 8:
            return None
        size, atom_type = struct.unpack(">I4s", header)
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return None
            size = struct.unpack(">Q", ext)[0]
            header_size = 16
        elif size == 0:
            size = end - f.tell() + 8
            header_size = 8
        else:
            header_size = 8
        body_size = size - header_size
        if body_size < 0:
            return None
        if atom_type == b"mvhd":
            return _parse_mvhd(f.read(body_size))
        if atom_type in _ISO_CONTAINERS:
            sub_end = f.tell() + body_size
            d = _walk_for_mvhd(f, end=sub_end)
            if d is not None:
                return d
            f.seek(sub_end)
        else:
            f.seek(body_size, 1)
    return None


def _parse_mvhd(data: bytes) -> Optional[float]:
    if len(data) < 4:
        return None
    version = data[0]
    if version == 1 and len(data) >= 1 + 3 + 8 + 8 + 4 + 8:
        # version(1) flags(3) ctime(8) mtime(8) timescale(4) duration(8)
        timescale = struct.unpack(">I", data[1 + 3 + 8 + 8:1 + 3 + 8 + 8 + 4])[0]
        duration = struct.unpack(">Q", data[1 + 3 + 8 + 8 + 4:1 + 3 + 8 + 8 + 4 + 8])[0]
    elif version == 0 and len(data) >= 1 + 3 + 4 + 4 + 4 + 4:
        timescale = struct.unpack(">I", data[1 + 3 + 4 + 4:1 + 3 + 4 + 4 + 4])[0]
        duration = struct.unpack(">I", data[1 + 3 + 4 + 4 + 4:1 + 3 + 4 + 4 + 4 + 4])[0]
    else:
        return None
    if timescale == 0:
        return None
    return duration / timescale


# ---------- ffmpeg/ffprobe fallback ----------

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")


def probe_with_ffmpeg(path: Path) -> dict:
    """Return {duration, width, height, has_audio, created_year} via ffprobe or ffmpeg -i."""
    info = {"duration": None, "width": None, "height": None, "has_audio": 0, "created_year": None}
    fp = _ffprobe_exe()
    if fp:
        try:
            r = subprocess.run(
                [fp, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                capture_output=True, timeout=60, creationflags=_SUBPROCESS_FLAGS,
            )
            if r.returncode == 0 and r.stdout:
                data = json.loads(r.stdout)
                fmt = data.get("format", {})
                dur = fmt.get("duration")
                if dur:
                    info["duration"] = float(dur)
                created = fmt.get("tags", {}).get("creation_time")
                if created:
                    try:
                        info["created_year"] = _dt.datetime.fromisoformat(created.replace("Z", "+00:00")).year
                    except ValueError:
                        pass
                for s in data.get("streams", []):
                    if s.get("codec_type") == "video":
                        info["width"] = info["width"] or s.get("width")
                        info["height"] = info["height"] or s.get("height")
                    elif s.get("codec_type") == "audio":
                        info["has_audio"] = 1
                return info
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            pass

    # Fallback: ffmpeg -i, parse stderr
    try:
        r = subprocess.run(
            [_FFMPEG, "-hide_banner", "-i", str(path)],
            capture_output=True, timeout=60, creationflags=_SUBPROCESS_FLAGS,
        )
        text = (r.stderr or b"").decode("utf-8", errors="replace")
        m = _DURATION_RE.search(text)
        if m:
            h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            info["duration"] = h * 3600 + mnt * 60 + s
        if "Audio:" in text:
            info["has_audio"] = 1
        size_match = re.search(r"Stream.*Video:.* (\d+)x(\d+)", text)
        if size_match:
            info["width"], info["height"] = int(size_match.group(1)), int(size_match.group(2))
        created = re.search(r"creation_time\s*:\s*(\S+)", text)
        if created:
            try:
                info["created_year"] = _dt.datetime.fromisoformat(created.group(1).replace("Z", "+00:00")).year
            except ValueError:
                pass
    except (subprocess.TimeoutExpired, OSError):
        pass
    return info


def probe(path: Path) -> dict:
    """Combined probe: fast MP4 duration + ffprobe for the rest. Always returns a dict."""
    info = probe_with_ffmpeg(path)
    if info.get("duration") is None:
        fast = mp4_duration(path)
        if fast is not None:
            info["duration"] = fast
    if info.get("created_year") is None:
        try:
            info["created_year"] = _dt.datetime.fromtimestamp(path.stat().st_mtime).year
        except OSError:
            pass
    return info
