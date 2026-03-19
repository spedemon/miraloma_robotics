"""
settings.py — Persistent settings cache

Saves and loads user-configurable settings to a JSON file in the
user's home directory so they survive across app restarts.
"""

import json
from pathlib import Path

SETTINGS_FILE = Path.home() / ".robot_command_center.json"

DEFAULTS = {
    "api_key": "",
    "model": "Gemini 2.5 Flash (Recommended)",
    "speed_seconds_per_foot": 3.0,
    "default_motor_speed": 150,
    "uart_port": "",
    "uart_baud": 115200,
    "robot": "",
}


def load_settings() -> dict:
    """Load settings from disk, falling back to defaults for missing keys."""
    settings = dict(DEFAULTS)
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE) as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for key in DEFAULTS:
                    if key in saved:
                        settings[key] = saved[key]
    except (json.JSONDecodeError, OSError):
        # Corrupt or unreadable file — use defaults
        pass
    return settings


def save_settings(data: dict) -> None:
    """Write settings to disk atomically."""
    # Merge with defaults so the file always has every key
    to_save = dict(DEFAULTS)
    to_save.update(data)
    try:
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(to_save, f, indent=2)
        tmp.replace(SETTINGS_FILE)
    except OSError:
        pass  # Best-effort; don't crash the app
