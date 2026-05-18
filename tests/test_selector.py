"""Tests for compile/selector.py against an in-memory cache."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from compilation_maker.compile.selector import select, Eligible
from compilation_maker.index.cache import Cache


@pytest.fixture
def cache_with_rows(tmp_path: Path):
    db = tmp_path / "test.sqlite"
    cache = Cache(db_path=db)

    def add(name, **kw):
        row = {
            "path": str(tmp_path / name),
            "size": 1024,
            "mtime": time.time(),
            "duration": 30.0,
            "has_audio": 1,
            "width": 1920,
            "height": 1080,
            "created_year": 2024,
            "nsfw_peak": 0.0,
            "nsfw_soft_count": 0,
            "face_max_count": 2,
            "motion_score": 0.1,
            "speech_fraction": 0.5,
            "error": None,
        }
        row.update(kw)
        cache.upsert(row)

    add("good_clip.mp4")
    add("nsfw_clip.mp4", nsfw_peak=0.95, nsfw_soft_count=6)
    add("static_wall.mp4", motion_score=0.001)
    add("silent_clip.mp4", speech_fraction=0.0, has_audio=0)
    add("sky_shot.mp4", face_max_count=0)
    add("tiny_clip.mp4", duration=2.0)
    add("errored.mp4", error="boom")
    yield cache, tmp_path
    cache.close()


def _filters(**overrides):
    f = {
        "min_duration": 5.5,
        "nsfw_mode": "exclude",
        "talking_required": True,
        # source filters off by default in these legacy tests so existing
        # fixture filenames (good_clip.mp4 etc.) keep passing. New tests
        # opt-in explicitly.
        "source_allowlist_strict": False,
        "exclude_vertical": False,
        "exclude_downloads": False,
        "exclude_low_resolution": False,
    }
    f.update(overrides)
    return f


_THRESHOLDS = {
    "nsfw_strict": 0.7,
    "nsfw_soft": 0.5,
    "nsfw_soft_min_frames": 3,
    "speech_fraction_min": 0.1,
    "motion_score_min": 0.02,
    "min_short_side": 720,
}


def test_default_filters_keep_expected(cache_with_rows):
    cache, root = cache_with_rows
    elig = select(cache, root, filters=_filters(), thresholds=_THRESHOLDS)
    names = sorted(Path(e.path).name for e in elig)
    # face/motion filters removed — sky_shot and static_wall now pass
    assert "good_clip.mp4" in names
    assert "sky_shot.mp4" in names
    assert "static_wall.mp4" in names
    assert "nsfw_clip.mp4" not in names
    assert "tiny_clip.mp4" not in names


def test_disabling_talking_recovers_silent(cache_with_rows):
    cache, root = cache_with_rows
    elig = select(cache, root, filters=_filters(talking_required=False), thresholds=_THRESHOLDS)
    names = sorted(Path(e.path).name for e in elig)
    assert "silent_clip.mp4" in names


def test_disabling_nsfw_keeps_nsfw(cache_with_rows):
    cache, root = cache_with_rows
    elig = select(cache, root, filters=_filters(nsfw_mode="off"), thresholds=_THRESHOLDS)
    names = sorted(Path(e.path).name for e in elig)
    assert "nsfw_clip.mp4" in names


def test_nsfw_only_mode(cache_with_rows):
    cache, root = cache_with_rows
    elig = select(cache, root, filters=_filters(nsfw_mode="only"), thresholds=_THRESHOLDS)
    names = sorted(Path(e.path).name for e in elig)
    assert names == ["nsfw_clip.mp4"]


def test_min_duration_drops_tiny(cache_with_rows):
    cache, root = cache_with_rows
    elig = select(cache, root, filters=_filters(), thresholds=_THRESHOLDS)
    assert all(e.duration >= 5.5 for e in elig)


def test_errored_rows_excluded(cache_with_rows):
    cache, root = cache_with_rows
    elig = select(cache, root, filters=_filters(nsfw_mode="off", talking_required=False),
                  thresholds=_THRESHOLDS)
    names = [Path(e.path).name for e in elig]
    assert "errored.mp4" not in names


# --- source filter integration -------------------------------------------

@pytest.fixture
def source_cache(tmp_path: Path):
    db = tmp_path / "src.sqlite"
    cache = Cache(db_path=db)

    def add(name, **kw):
        row = {
            "path": str(tmp_path / name),
            "size": 1024,
            "mtime": time.time(),
            "duration": 30.0,
            "has_audio": 1,
            "width": 1920,
            "height": 1080,
            "created_year": 2024,
            "nsfw_peak": 0.0,
            "nsfw_soft_count": 0,
            "face_max_count": 2,
            "motion_score": 0.1,
            "speech_fraction": 0.5,
            "error": None,
        }
        row.update(kw)
        cache.upsert(row)

    add("GX010001.mp4")
    add("IMG_4242.mov")
    add("PXL_20240101_120000.mp4")
    add("random_clip.mp4")
    add("7123456789012345678.mp4")
    add("tiktok_dl.mp4")
    add("portrait.mp4", width=1080, height=1920)  # vertical
    add("tiny.mp4", width=640, height=360)        # low-res
    add("GX020002.mp4")  # second valid camera clip
    yield cache, tmp_path
    cache.close()


def test_strict_source_keeps_only_camera_filenames(source_cache):
    cache, root = source_cache
    elig = select(cache, root,
                  filters=_filters(source_allowlist_strict=True),
                  thresholds=_THRESHOLDS)
    names = sorted(Path(e.path).name for e in elig)
    # portrait.mp4 and tiny.mp4 also fail the allowlist (not camera names),
    # so strict mode rejects them too.
    assert names == ["GX010001.mp4", "GX020002.mp4", "IMG_4242.mov",
                     "PXL_20240101_120000.mp4"]


def test_denylist_blocks_tiktok_without_strict_mode(source_cache):
    cache, root = source_cache
    elig = select(cache, root,
                  filters=_filters(exclude_downloads=True),
                  thresholds=_THRESHOLDS)
    names = {Path(e.path).name for e in elig}
    assert "7123456789012345678.mp4" not in names
    assert "tiktok_dl.mp4" not in names
    assert "random_clip.mp4" in names  # unknown still allowed when strict off


def test_vertical_filter_drops_portrait(source_cache):
    cache, root = source_cache
    elig = select(cache, root,
                  filters=_filters(exclude_vertical=True),
                  thresholds=_THRESHOLDS)
    names = {Path(e.path).name for e in elig}
    assert "portrait.mp4" not in names


def test_low_resolution_filter_drops_tiny(source_cache):
    cache, root = source_cache
    elig = select(cache, root,
                  filters=_filters(exclude_low_resolution=True),
                  thresholds=_THRESHOLDS)
    names = {Path(e.path).name for e in elig}
    assert "tiny.mp4" not in names


def test_all_source_filters_combined(source_cache):
    cache, root = source_cache
    elig = select(cache, root, filters=_filters(
        source_allowlist_strict=True,
        exclude_vertical=True,
        exclude_downloads=True,
        exclude_low_resolution=True,
    ), thresholds=_THRESHOLDS)
    names = sorted(Path(e.path).name for e in elig)
    assert names == ["GX010001.mp4", "GX020002.mp4", "IMG_4242.mov",
                     "PXL_20240101_120000.mp4"]


def test_report_collects_reasons(source_cache):
    cache, root = source_cache
    report: dict = {}
    select(cache, root, filters=_filters(
        source_allowlist_strict=True,
        exclude_vertical=True,
        exclude_downloads=True,
        exclude_low_resolution=True,
    ), thresholds=_THRESHOLDS, report=report)
    counts = report["counts"]
    assert counts.get("tiktok_id", 0) >= 1
    assert counts.get("tiktok", 0) >= 1
    assert counts.get("vertical", 0) >= 1
    assert counts.get("low_resolution", 0) >= 1
    assert counts.get("not_in_allowlist", 0) >= 1
    samples = report["samples"]
    assert any("portrait" in p for p in samples["vertical"])
