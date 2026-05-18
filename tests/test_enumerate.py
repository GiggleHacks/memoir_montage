from __future__ import annotations

from pathlib import Path

from compilation_maker.index.enumerate import iter_videos, VIDEO_EXTS


def test_extensions_picked_up(tmp_path: Path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.MOV").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.mkv").write_bytes(b"x")
    (tmp_path / "ignore.txt").write_bytes(b"x")
    (tmp_path / "ignore.jpg").write_bytes(b"x")

    found = sorted(p.name.lower() for p in iter_videos(tmp_path))
    assert found == ["a.mp4", "b.mov", "c.mkv"]


def test_all_known_exts_lowercase():
    for ext in VIDEO_EXTS:
        assert ext == ext.lower()
        assert ext.startswith(".")
