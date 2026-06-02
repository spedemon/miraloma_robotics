#!/usr/bin/env python3
"""
main.py — Robot Mind: Mission Control UI (Entry Point)

Orchestrates the application: initialises shared state, mounts static
files, builds the UI, wires handlers, and starts the NiceGUI server.

All UI construction lives in ui_layout.py, all event handlers in
handlers.py, robot discovery in robot_discovery.py.
"""

import argparse
from pathlib import Path

from nicegui import ui, app

from robot_hal import RobotHAL
from gemini_client import GeminiClient, AVAILABLE_MODELS
import nav_runtime
from settings import load_settings
from robot_discovery import (
    PLATFORM_INFO,
    discover_robots,
    load_robot_config,
    load_robot_firmware,
    build_and_set_prompt,
)
import handlers
import ui_layout


# ── Paths ─────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
ROBOTS_DIR = BASE_DIR / "robots_firmware"
LOGO_URL = "/static/logo.png"

# Serve static assets (logo, CSS, JS, SVG, etc.)
app.add_static_files('/static', str(BASE_DIR / 'static'))

# WAV clips for TTS are written to static/tts/
_TTS_DIR = BASE_DIR / 'static' / 'tts'
_TTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Shared Services ───────────────────────────────────────────────
robot = RobotHAL()
gemini = GeminiClient()
nav_runtime._set_robot(robot)

# ── Load cached settings ─────────────────────────────────────────
_saved = load_settings()
calibration = {
    "speed_seconds_per_foot": _saved["speed_seconds_per_foot"],
    "default_motor_speed": _saved["default_motor_speed"],
}

# ── Discover & select robot ──────────────────────────────────────
available_robots = discover_robots(ROBOTS_DIR)
selected_robot: str = (
    _saved["robot"] if _saved["robot"] in available_robots
    else (available_robots[0] if available_robots else "")
)

# Pre-load initial robot data
_initial_config = load_robot_config(ROBOTS_DIR, selected_robot) if selected_robot else {}
_initial_firmware, _initial_filename = load_robot_firmware(ROBOTS_DIR, selected_robot) if selected_robot else ("", "")
_initial_platform = PLATFORM_INFO.get(
    _initial_config.get("firmware_platform", ""), PLATFORM_INFO.get("microbit")
)

# Build initial system prompt for the selected robot
if selected_robot:
    build_and_set_prompt(ROBOTS_DIR, selected_robot, gemini, robot, calibration, nav_runtime)

# Auto-configure Gemini if an API key was previously saved
if _saved["api_key"]:
    try:
        gemini.configure(api_key=_saved["api_key"])
        if _saved["model"] in AVAILABLE_MODELS:
            gemini.model_label = _saved["model"]
        if selected_robot:
            build_and_set_prompt(ROBOTS_DIR, selected_robot, gemini, robot, calibration, nav_runtime)
    except Exception:
        pass  # Key might be stale; user can re-enter

# ── Build UI ──────────────────────────────────────────────────────
ui_refs = ui_layout.build_ui(
    logo_url=LOGO_URL,
    selected_robot=selected_robot,
    available_robots=available_robots,
    initial_config=_initial_config,
    initial_firmware=_initial_firmware,
    initial_filename=_initial_filename,
    initial_platform=_initial_platform,
    robot_hal=robot,
    gemini_client=gemini,
    calibration=calibration,
    saved=_saved,
    current_code="# No navigation script loaded yet.",
)

# ── Wire handlers ─────────────────────────────────────────────────
handlers.init(
    robot_hal=robot,
    gemini_client=gemini,
    refs=ui_refs,
    robots_firmware_dir=ROBOTS_DIR,
    tts_audio_dir=_TTS_DIR,
    cal=calibration,
    initial_robot=selected_robot,
    saved_settings=_saved,
)

# ── Launch ────────────────────────────────────────────────────────
if __name__ in {"__main__", "__mp_main__"}:
    parser = argparse.ArgumentParser(description="Miraloma Robot Brain Designer")
    parser.add_argument("-p", "--port", type=int, default=8080, help="Port to run the UI on (default: 8080)")
    parser.add_argument("-n", "--native", action="store_true", help="Run in native window mode")
    args = parser.parse_args()

    ui.run(
        title="Miraloma Robots",
        favicon=str(BASE_DIR / 'static' / 'logo.png'),
        host="0.0.0.0",
        port=args.port,
        native=args.native,
        dark=False,
        reload=not args.native,
    )
