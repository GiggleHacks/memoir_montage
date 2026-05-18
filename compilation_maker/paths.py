"""Centralized paths: settings dir, cache db, temp scratch."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def appdata_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_path() -> Path:
    return appdata_dir() / "settings.json"


def cache_db_path() -> Path:
    return appdata_dir() / "index.sqlite"


def models_dir() -> Path:
    d = appdata_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def compile_tmp_root() -> Path:
    return Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp")


def compile_tmp_dir(run_id: str) -> Path:
    d = compile_tmp_root() / f"compilation_maker_{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d
