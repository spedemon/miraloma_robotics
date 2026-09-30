"""Filesystem locations shared by the web and desktop entry points."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Mira"
SOURCE_DIR = Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """Return a bundled read-only resource path."""
    return SOURCE_DIR.joinpath(*parts)


def user_data_dir() -> Path:
    """Return Mira's per-user writable data directory."""
    override = os.environ.get("MIRA_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        path = (Path(base) if base else Path.home() / "AppData" / "Local") / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME")
        path = (Path(base).expanduser() if base else Path.home() / ".local" / "share") / APP_NAME.lower()

    path.mkdir(parents=True, exist_ok=True)
    return path
