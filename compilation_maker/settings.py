"""Settings persistence with sensible defaults and shallow merge on load."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .paths import settings_path


FILTER_PRESETS: dict[str, dict[str, Any]] = {
    "strict": {
        "min_duration": 5.5,
        "talking_required": True,
        "source_allowlist_strict": True,
        "exclude_vertical": True,
        "exclude_downloads": True,
        "exclude_low_resolution": True,
    },
    "normal": {
        "min_duration": 5.5,
        "talking_required": False,
        "source_allowlist_strict": False,
        "exclude_vertical": True,
        "exclude_downloads": True,
        "exclude_low_resolution": True,
    },
    "off": {
        "min_duration": 0,
        "talking_required": False,
        "source_allowlist_strict": False,
        "exclude_vertical": False,
        "exclude_downloads": False,
        "exclude_low_resolution": False,
    },
}

DEFAULTS: dict[str, Any] = {
    "last_folder": None,
    "filters": {
        "preset": "strict",
        "nsfw_mode": "exclude",
    },
    "thresholds": {
        "nsfw_strict": 0.70,
        "nsfw_soft": 0.50,
        "nsfw_soft_min_frames": 3,
        "speech_fraction_min": 0.10,
        "motion_score_min": 0.02,
        "min_short_side": 720,
    },
    "output": {
        "grid": 3,
        "total_seconds": 120,
        "swap_seconds": 5,
        "border": True,
        "filename_label": True,
        "year_label": True,
        "resolution": [1920, 1080],
        "fps": 30,
        "auto_open": True,
        "compile_workers": 0,
    },
    "indexer": {
        "sample_count": 8,
        "trim_pct": 0.05,
        "max_workers": 2,
        "device": "auto",
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    p = settings_path()
    if not p.exists():
        return deepcopy(DEFAULTS)
    try:
        with p.open("r", encoding="utf-8") as f:
            user = json.load(f)
    except (json.JSONDecodeError, OSError):
        return deepcopy(DEFAULTS)
    return _merge(DEFAULTS, user)


def save(settings: dict) -> None:
    p = settings_path()
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    tmp.replace(p)


def resolve_filters(settings: dict) -> dict:
    """Expand a filter preset name into the full boolean dict.

    Handles both new-style ``{"preset": "strict"}`` and old-style flat
    boolean dicts (backwards compat).  NSFW mode is stored separately
    from presets as ``filters.nsfw_mode`` ("exclude" | "off" | "only").
    """
    filters = settings.get("filters", {})
    preset = filters.get("preset")
    if preset == "custom":
        # Custom: start from "normal" defaults, then overlay any explicit flags
        # the user toggled (the UI sends them alongside preset=custom).
        result = deepcopy(FILTER_PRESETS["normal"])
        for k in (
            "talking_required", "source_allowlist_strict",
            "exclude_vertical", "exclude_downloads", "exclude_low_resolution",
        ):
            if k in filters:
                result[k] = bool(filters[k])
        if "min_duration" in filters:
            try:
                result["min_duration"] = float(filters["min_duration"])
            except (TypeError, ValueError):
                pass
    elif preset and preset in FILTER_PRESETS:
        result = deepcopy(FILTER_PRESETS[preset])
    elif any(isinstance(v, bool) for v in filters.values()):
        result = dict(filters)
    else:
        result = deepcopy(FILTER_PRESETS["strict"])

    # NSFW mode — separate from presets
    if "nsfw_mode" in filters:
        result["nsfw_mode"] = filters["nsfw_mode"]
    elif "nsfw_exclude" in result:
        result["nsfw_mode"] = "exclude" if result.pop("nsfw_exclude") else "off"
    else:
        result["nsfw_mode"] = "exclude"
    result.pop("nsfw_exclude", None)
    # Remove legacy keys that no longer exist
    result.pop("face_required", None)
    result.pop("motion_required", None)
    return result
