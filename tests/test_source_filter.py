"""Unit tests for compile/source_filter.classify()."""
from __future__ import annotations

import pytest

from compilation_maker.compile.source_filter import classify


_DEFAULT_KW = dict(
    exclude_downloads=True,
    exclude_vertical=True,
    exclude_low_resolution=True,
    source_allowlist_strict=True,
    min_short_side=720,
)


def _classify(path, w=1920, h=1080, **overrides):
    kw = {**_DEFAULT_KW, **overrides}
    return classify(path, w, h, **kw)


@pytest.mark.parametrize("name", [
    "GX010123.MP4",
    "GH010001.mp4",
    "GOPR1234.MP4",
    "GP123456.mp4",
    "IMG_4242.MOV",
    "IMG_0001.mp4",
    "PXL_20240101_123456.mp4",
    "PXL_20240101_123456789.mp4",
    "VID_20231201_184500.mp4",
    "DSC_0123.MOV",
    "MVI_4567.MP4",
    "C0001.MP4",
])
def test_allowlist_matches(name):
    allowed, reason = _classify(f"/x/{name}")
    assert allowed, f"{name} should be allowed (got {reason})"


@pytest.mark.parametrize("name,expected", [
    ("7123456789012345678.mp4", "tiktok_id"),
    ("tiktok_abc.mp4", "tiktok"),
    ("ssstik_dl.mp4", "tiktok"),
    ("video_download.mp4", "downloader"),
    ("yt-dlp_clip.mp4", "downloader"),
    ("ssstwitter_xyz.mp4", "downloader"),
    ("savefrom_clip.mp4", "downloader"),
    ("a1b2c3d4-e5f6-7890-abcd-ef0123456789.mp4", "uuid"),
])
def test_denylist_matches(name, expected):
    allowed, reason = _classify(f"/x/{name}")
    assert not allowed
    assert reason == expected


def test_vertical_rejected():
    allowed, reason = _classify("/x/GX010001.mp4", w=1080, h=1920)
    assert not allowed
    assert reason == "vertical"


def test_horizontal_kept():
    allowed, reason = _classify("/x/GX010001.mp4", w=1920, h=1080)
    assert allowed


def test_low_resolution_rejected():
    allowed, reason = _classify("/x/GX010001.mp4", w=854, h=480)
    assert not allowed
    assert reason == "low_resolution"


def test_720_kept():
    allowed, _ = _classify("/x/GX010001.mp4", w=1280, h=720)
    assert allowed


def test_strict_mode_rejects_unknown_filename():
    allowed, reason = _classify("/x/random_name.mp4")
    assert not allowed
    assert reason == "not_in_allowlist"


def test_non_strict_mode_keeps_unknown_filename():
    allowed, reason = _classify(
        "/x/random_name.mp4", source_allowlist_strict=False
    )
    assert allowed
    assert reason is None


def test_denylist_runs_even_with_strict_off():
    allowed, reason = _classify(
        "/x/tiktok_dl.mp4", source_allowlist_strict=False
    )
    assert not allowed
    assert reason == "tiktok"


def test_disabling_vertical_allows_portrait():
    allowed, _ = _classify(
        "/x/GX010001.mp4", w=1080, h=1920, exclude_vertical=False
    )
    assert allowed


def test_disabling_lowres_allows_small():
    allowed, _ = _classify(
        "/x/GX010001.mp4", w=640, h=360, exclude_low_resolution=False
    )
    assert allowed


def test_case_insensitive_allowlist():
    allowed, _ = _classify("/x/gx010123.mp4")
    assert allowed


def test_missing_dimensions_skips_geometric_checks():
    # When width/height are None (rare but possible), don't reject on geometry.
    allowed, reason = _classify(
        "/x/GX010001.mp4", w=None, h=None,
    )
    assert allowed
