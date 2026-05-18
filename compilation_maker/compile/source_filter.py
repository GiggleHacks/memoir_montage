"""Filename + geometry classifier for excluding non-camera clips.

Pure functions over data already in the index cache (path, width, height).
No probing, no I/O. Returns (allowed, reason) so callers can aggregate counts.
"""
from __future__ import annotations

import re
from pathlib import Path

# --- pattern tables --------------------------------------------------------

_ALLOWLIST: list[tuple[str, re.Pattern[str]]] = [
    ("gopro",   re.compile(r"^(GX|GH|GOPR|GP)\d+\.(mp4|mov|360)$", re.IGNORECASE)),
    ("iphone",  re.compile(r"^IMG_\d{4}\.(mov|mp4|heic|hevc)$", re.IGNORECASE)),
    ("android", re.compile(r"^(PXL|VID)_\d{8}_\d{6}.*\.(mp4|mov)$", re.IGNORECASE)),
    ("dslr",    re.compile(
        r"^(DSC|MVI|MAH|MAQ|_DSC|_MG_|C\d{3,4})_?\d*\.(mp4|mov|mts|m2ts)$",
        re.IGNORECASE,
    )),
]

_DENY_REGEX: list[tuple[str, re.Pattern[str]]] = [
    ("tiktok_id", re.compile(r"^\d{16,}\.", re.IGNORECASE)),
    ("uuid",      re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE,
    )),
    # Random hex/alphanumeric gibberish (32+ chars with no separators or
    # structure — typical of auto-generated download filenames)
    ("gibberish", re.compile(r"^[0-9a-f]{32,}\.", re.IGNORECASE)),
    # Mixed alphanumeric gibberish (20+ chars, no underscores/dashes/spaces)
    ("gibberish", re.compile(r"^[0-9a-zA-Z]{20,}\.(mp4|mov|avi|mkv|webm)$")),
]

_DENY_SUBSTRINGS: list[tuple[str, tuple[str, ...]]] = [
    ("tiktok",     ("tiktok", "ssstik", "snaptik", "musically", "douyin")),
    ("downloader", (
        "download", "ytdlp", "yt-dlp", "youtube",
        "ssstwitter", "savefrom", "twitter_", "reddit_save",
        "redditsave", "instagram_", "ig_save",
        "streamable", "tenor", "giphy", "gfycat",
        "v.redd.it", "fb_video", "fbvideo",
    )),
]


def _matches_allowlist(basename: str) -> str | None:
    for label, rx in _ALLOWLIST:
        if rx.match(basename):
            return label
    return None


def _matches_denylist(basename: str) -> str | None:
    low = basename.lower()
    for label, rx in _DENY_REGEX:
        if rx.match(basename):
            return label
    for label, needles in _DENY_SUBSTRINGS:
        for needle in needles:
            if needle in low:
                return label
    return None


def classify(
    path: str,
    width: int | None,
    height: int | None,
    *,
    exclude_downloads: bool,
    exclude_vertical: bool,
    exclude_low_resolution: bool,
    source_allowlist_strict: bool,
    min_short_side: int,
) -> tuple[bool, str | None]:
    """Return (allowed, reason). reason is None when allowed."""
    basename = Path(path).name

    if exclude_downloads:
        hit = _matches_denylist(basename)
        if hit is not None:
            return False, hit

    if exclude_vertical and width and height and height > width:
        return False, "vertical"

    if exclude_low_resolution and width and height:
        if min(width, height) < int(min_short_side):
            return False, "low_resolution"

    if source_allowlist_strict:
        if _matches_allowlist(basename) is None:
            return False, "not_in_allowlist"

    return True, None
