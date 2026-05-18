"""Tests for the pure-Python MP4 duration probe.

Uses imageio_ffmpeg's bundled ffmpeg to synthesize a tiny test mp4 at module setup.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = None


_FLAGS = 0
if sys.platform == "win32":
    _FLAGS = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def tiny_mp4(tmp_path_factory) -> Path:
    if FFMPEG is None:
        pytest.skip("ffmpeg not available")
    out = tmp_path_factory.mktemp("mp4") / "tiny.mp4"
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=128x96:d=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=_FLAGS)
    if r.returncode != 0:
        pytest.skip(f"ffmpeg test fixture failed: {r.stderr!r}")
    return out


def test_mp4_duration_atom_parser(tiny_mp4):
    from compilation_maker.index.probe import mp4_duration
    d = mp4_duration(tiny_mp4)
    assert d is not None
    assert 2.5 <= d <= 3.5


def test_probe_combined(tiny_mp4):
    from compilation_maker.index.probe import probe
    info = probe(tiny_mp4)
    assert info["duration"] is not None
    assert 2.5 <= info["duration"] <= 3.5
    assert info["width"] == 128
    assert info["height"] == 96


def test_mp4_duration_returns_none_on_nonmp4(tmp_path):
    from compilation_maker.index.probe import mp4_duration
    p = tmp_path / "not_a_video.txt"
    p.write_bytes(b"hello world")
    assert mp4_duration(p) is None
