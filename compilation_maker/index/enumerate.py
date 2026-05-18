"""Recursive enumeration of video files under a root."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator


VIDEO_EXTS = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg",
})


def iter_videos(root: Path) -> Iterator[Path]:
    root = Path(root).resolve()
    if not root.exists():
        return
    if root.is_file():
        if root.suffix.lower() in VIDEO_EXTS:
            yield root
        return
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                yield p
        except OSError:
            continue
