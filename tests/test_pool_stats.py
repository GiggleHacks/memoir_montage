"""Unit tests for the validation-driven compile config (Iteration 5).

Covers pool_stats(), compile_constraints(), validate_compile_options() across
the empty / impossible / limited / ready scenarios.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from compilation_maker.compile.selector import (
    compile_constraints,
    pool_stats,
    validate_compile_options,
)
from compilation_maker.index.cache import Cache


_FILTERS = {
    "min_duration": 5.5,
    "nsfw_mode": "off",
    "talking_required": False,
    # Source filters off so the generic "clip_NN.mp4" fixture names pass.
    "source_allowlist_strict": False,
    "exclude_vertical": False,
    "exclude_downloads": False,
    "exclude_low_resolution": False,
}
_THRESHOLDS = {
    "nsfw_strict": 0.7,
    "nsfw_soft": 0.5,
    "nsfw_soft_min_frames": 3,
    "speech_fraction_min": 0.1,
    "motion_score_min": 0.02,
    "min_short_side": 720,
}


@pytest.fixture
def cache_factory(tmp_path: Path):
    def _build(rows):
        cache = Cache(db_path=tmp_path / "c.sqlite")
        for i, kw in enumerate(rows):
            row = {
                "path": str(tmp_path / f"clip_{i:02d}.mp4"),
                "size": 1024,
                "mtime": time.time(),
                "duration": 20.0,
                "has_audio": 1,
                "width": 1920, "height": 1080,
                "created_year": 2024,
                "nsfw_peak": 0.0, "nsfw_soft_count": 0,
                "face_max_count": 1,
                "motion_score": 0.1,
                "speech_fraction": 0.5,
                "error": None,
            }
            row.update(kw)
            cache.upsert(row)
        return cache, tmp_path
    return _build


def test_empty_pool(tmp_path):
    cache = Cache(db_path=tmp_path / "c.sqlite")
    s = pool_stats(cache, tmp_path, filters=_FILTERS, thresholds=_THRESHOLDS, swap_seconds=5)
    assert s.unique_clips == 0
    assert s.available_seconds == 0.0


def test_pool_stats_basic(cache_factory):
    cache, root = cache_factory([{"duration": 10.0}, {"duration": 20.0}, {"duration": 30.0}])
    s = pool_stats(cache, root, filters=_FILTERS, thresholds=_THRESHOLDS, swap_seconds=5)
    assert s.unique_clips == 3
    assert s.available_seconds == 60.0
    assert s.longest_seconds == 30.0
    assert s.shortest_seconds == 10.0


def test_pool_stats_short_clips_excluded(cache_factory):
    cache, root = cache_factory([
        {"duration": 30.0}, {"duration": 6.0}, {"duration": 4.0},
    ])
    # swap=5 → min usable = 5.5; only 30s and 6s qualify
    s = pool_stats(cache, root, filters=_FILTERS, thresholds=_THRESHOLDS, swap_seconds=5)
    assert s.unique_clips == 2
    assert s.available_seconds == 36.0


def test_pool_stats_audioless_excluded(cache_factory):
    cache, root = cache_factory([
        {"duration": 30.0, "has_audio": 1},
        {"duration": 30.0, "has_audio": 0},
    ])
    s = pool_stats(cache, root, filters=_FILTERS, thresholds=_THRESHOLDS, swap_seconds=5)
    assert s.unique_clips == 1
    assert s.available_seconds == 30.0


def test_compile_constraints_recommended(cache_factory):
    cache, root = cache_factory([{"duration": 30.0}] * 12)
    c = compile_constraints(cache, root, filters=_FILTERS, thresholds=_THRESHOLDS, swap_seconds=5)
    assert c["unique_clips"] == 12
    assert c["available_seconds"] == 360.0
    # 12 clips → 3x3 fits (9), 4x4 needs 16 → disabled
    assert c["max_grid"] == 3
    assert "4" in c["tooltips"]
    assert "5" in c["tooltips"]
    assert "3" not in c["tooltips"]
    assert c["recommended"]["grid"] == 3


def test_compile_constraints_no_recommendation_when_empty(cache_factory):
    cache, root = cache_factory([])
    c = compile_constraints(cache, root, filters=_FILTERS, thresholds=_THRESHOLDS, swap_seconds=5)
    assert c["max_grid"] == 0
    assert c["recommended"] == {}
    assert "3" in c["tooltips"]


def test_validate_impossible_empty(cache_factory):
    cache, root = cache_factory([])
    v = validate_compile_options(
        cache, root, filters=_FILTERS, thresholds=_THRESHOLDS,
        grid=3, total_seconds=30, swap_seconds=5,
    )
    assert v["status"] == "impossible"
    assert v["reasons"]


def test_validate_impossible_grid_too_big(cache_factory):
    cache, root = cache_factory([{"duration": 30.0}] * 4)
    v = validate_compile_options(
        cache, root, filters=_FILTERS, thresholds=_THRESHOLDS,
        grid=3, total_seconds=30, swap_seconds=5,
    )
    assert v["status"] == "impossible"
    assert any("unique clips" in r for r in v["reasons"])


def test_validate_ready(cache_factory):
    cache, root = cache_factory([{"duration": 30.0}] * 12)
    # 3x3 (9 cells), 10s output → used = 10 * 9 = 90s ≤ 360s available
    v = validate_compile_options(
        cache, root, filters=_FILTERS, thresholds=_THRESHOLDS,
        grid=3, total_seconds=10, swap_seconds=5,
    )
    assert v["status"] == "ready"
    assert v["used_seconds"] == 90.0
    assert v["available_seconds"] == 360.0


def test_validate_limited_warns_about_repetition(cache_factory):
    cache, root = cache_factory([{"duration": 10.0}] * 9)
    # 3x3 (9 cells), 60s output → used = 60 * 9 = 540s > 90s available
    v = validate_compile_options(
        cache, root, filters=_FILTERS, thresholds=_THRESHOLDS,
        grid=3, total_seconds=60, swap_seconds=5,
    )
    assert v["status"] == "limited"
    assert v["warnings"]


def test_max_total_for_grid(cache_factory):
    cache, root = cache_factory([{"duration": 30.0}] * 9)
    # 3x3 = 9 cells. available = 270s. max output = 270/9 = 30s.
    v = validate_compile_options(
        cache, root, filters=_FILTERS, thresholds=_THRESHOLDS,
        grid=3, total_seconds=30, swap_seconds=5,
    )
    assert abs(v["max_total_for_grid"] - 30.0) < 1e-6
