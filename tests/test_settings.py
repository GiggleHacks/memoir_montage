from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from compilation_maker import settings


def test_defaults_returned_when_no_file(tmp_path: Path):
    with mock.patch("compilation_maker.settings.settings_path", return_value=tmp_path / "nope.json"):
        s = settings.load()
    assert s["filters"]["preset"] == "strict"
    assert s["output"]["grid"] == 3


def test_user_overrides_merge(tmp_path: Path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"filters": {"preset": "normal"}, "output": {"grid": 5}}))
    with mock.patch("compilation_maker.settings.settings_path", return_value=p):
        s = settings.load()
    assert s["filters"]["preset"] == "normal"
    assert s["output"]["grid"] == 5
    assert s["output"]["fps"] == 30


def test_save_roundtrip(tmp_path: Path):
    p = tmp_path / "settings.json"
    payload = {"last_folder": "C:/videos", "output": {"grid": 6}}
    with mock.patch("compilation_maker.settings.settings_path", return_value=p):
        settings.save(payload)
        loaded = settings.load()
    assert loaded["last_folder"] == "C:/videos"
    assert loaded["output"]["grid"] == 6


def test_resolve_filters_preset():
    s = {"filters": {"preset": "strict", "nsfw_mode": "exclude"}}
    f = settings.resolve_filters(s)
    assert f["nsfw_mode"] == "exclude"
    assert f["talking_required"] is True
    assert f["exclude_vertical"] is True
    assert "face_required" not in f
    assert "motion_required" not in f


def test_resolve_filters_normal():
    s = {"filters": {"preset": "normal"}}
    f = settings.resolve_filters(s)
    assert f["exclude_vertical"] is True
    assert f["talking_required"] is False


def test_resolve_filters_off():
    s = {"filters": {"preset": "off"}}
    f = settings.resolve_filters(s)
    assert f["talking_required"] is False
    assert f["exclude_vertical"] is False
    assert f["exclude_downloads"] is False


def test_resolve_filters_nsfw_mode_only():
    s = {"filters": {"preset": "off", "nsfw_mode": "only"}}
    f = settings.resolve_filters(s)
    assert f["nsfw_mode"] == "only"


def test_resolve_filters_backwards_compat():
    s = {"filters": {
        "nsfw_exclude": True, "face_required": False,
        "talking_required": True, "motion_required": True,
    }}
    f = settings.resolve_filters(s)
    assert f["nsfw_mode"] == "exclude"
    assert "face_required" not in f
    assert "motion_required" not in f


def test_resolve_filters_unknown_preset_defaults_strict():
    s = {"filters": {"preset": "nonexistent"}}
    f = settings.resolve_filters(s)
    assert f["nsfw_mode"] == "exclude"
