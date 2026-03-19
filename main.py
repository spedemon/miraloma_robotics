#!/usr/bin/env python3
"""
main.py — Robot Mind: Mission Control UI

NiceGUI application with 4 tabs:
  1. Workspace  — Chat + live code viewer + emergency stop
  2. Firmware   — Read-only firmware source (loaded from selected robot)
  3. Protocol   — Auto-generated command reference (from robot's protocol.yaml)
  4. Settings   — Robot type, serial port, baud rate, API key
"""

import json
import asyncio
import yaml
import threading
from datetime import datetime
from pathlib import Path

from nicegui import ui, app

# BASE_DIR must be defined before mounting static files
_BASE_DIR_EARLY = Path(__file__).parent

# Serve static assets (logo, etc.)
app.add_static_files('/static', str(_BASE_DIR_EARLY / 'static'))

from robot_hal import RobotHAL
from gemini_client import GeminiClient, AVAILABLE_MODELS, DEFAULT_MODEL_LABEL
from gemini_client import ResponseType, ParsedResponse
import nav_runtime
from settings import load_settings, save_settings

# ── Globals ───────────────────────────────────────────────────────
BASE_DIR = _BASE_DIR_EARLY
ROBOTS_DIR = BASE_DIR / "robots_firmware"
robot = RobotHAL()
gemini = GeminiClient()

# Wire the nav_runtime to use the shared robot HAL
nav_runtime._set_robot(robot)

LOGO_URL = "/static/logo.png"

# Chat history: list of {"role": "user"|"assistant", "text": str, "time": str}
chat_history: list[dict] = []
# Currently displayed navigation code
current_code: str = "# No navigation script loaded yet."
# Execution state
_running_task: asyncio.Task | None = None
_execution_lock = threading.Lock()

# ── Load cached settings ─────────────────────────────────────────
_saved = load_settings()

# Calibration parameters (from cache)
calibration = {
    "speed_seconds_per_foot": _saved["speed_seconds_per_foot"],
    "default_motor_speed": _saved["default_motor_speed"],
}


# ══════════════════════════════════════════════════════════════════
#  ROBOT DISCOVERY & LOADING
# ══════════════════════════════════════════════════════════════════

def discover_robots() -> list[str]:
    """Scan robots_firmware/ for subdirectories that contain a protocol.yaml."""
    robots = []
    if ROBOTS_DIR.is_dir():
        for child in sorted(ROBOTS_DIR.iterdir()):
            if child.is_dir() and (child / "protocol.yaml").exists():
                robots.append(child.name)
    return robots


def load_robot_config(robot_name: str) -> dict:
    """Load and return the protocol.yaml for the given robot."""
    path = ROBOTS_DIR / robot_name / "protocol.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f)
    return {}


def load_robot_firmware(robot_name: str) -> tuple[str, str]:
    """Load the main firmware source file for the given robot.

    Returns (source_code, filename).
    Looks for common firmware file extensions.
    """
    robot_dir = ROBOTS_DIR / robot_name
    for ext in (".ts", ".c", ".cpp", ".ino", ".py"):
        for fpath in robot_dir.glob(f"*{ext}"):
            if fpath.name.startswith("protocol"):
                continue
            return fpath.read_text(), fpath.name
    return "// No firmware source file found.", "unknown"


def load_robot_architecture(robot_name: str) -> str:
    """Load the robot_architecture.md file for context."""
    path = ROBOTS_DIR / robot_name / "robot_architecture.md"
    if path.exists():
        return path.read_text()
    return f"Robot: {robot_name}. No detailed architecture available."


def build_and_set_prompt(robot_name: str) -> None:
    """Build and set the system prompt for the selected robot."""
    config = load_robot_config(robot_name)
    architecture = load_robot_architecture(robot_name)
    prompt = GeminiClient.build_system_prompt(
        robot_name=config.get("name", robot_name.capitalize()),
        architecture_md=architecture,
        protocol_yaml=config,
        calibration=calibration,
    )
    gemini.set_system_prompt(prompt)

    # Also load protocol into HAL
    protocol_path = ROBOTS_DIR / robot_name / "protocol.yaml"
    if protocol_path.exists():
        robot.load_protocol(protocol_path)


# ══════════════════════════════════════════════════════════════════
#  HELPERS (must be defined before UI construction)
# ══════════════════════════════════════════════════════════════════

def _escape_html(text: str) -> str:
    """Escape HTML special characters for safe display."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_protocol_table(config: dict) -> str:
    """Build an HTML table from a robot's protocol.yaml setters and getters."""
    rows = ""

    for cmd in config.get("setters", []):
        params = ", ".join(
            f'{p["name"]}: {p["type"]}' for p in cmd.get("parameters", [])
        )
        rows += f"""
        <tr>
            <td><code>{_escape_html(cmd.get('id', ''))}</code></td>
            <td><code>{_escape_html(cmd.get('command', ''))}</code></td>
            <td>{_escape_html(cmd.get('description', ''))}</td>
            <td><span class="cmd-type cmd-setter">Setter</span></td>
            <td>{_escape_html(params) if params else '—'}</td>
        </tr>
        """

    for cmd in config.get("getters", []):
        params = ", ".join(
            f'{p["name"]}: {p["type"]}' for p in cmd.get("parameters", [])
        )
        returns = cmd.get("returns", {})
        ret_str = f' → {returns.get("type", "")}' if returns else ""
        rows += f"""
        <tr>
            <td><code>{_escape_html(cmd.get('id', ''))}</code></td>
            <td><code>{_escape_html(cmd.get('command', ''))}</code></td>
            <td>{_escape_html(cmd.get('description', ''))}{_escape_html(ret_str)}</td>
            <td><span class="cmd-type cmd-getter">Getter</span></td>
            <td>{_escape_html(params) if params else '—'}</td>
        </tr>
        """

    return f"""
    <table class="protocol-table">
        <thead>
            <tr>
                <th>ID</th>
                <th>UART Command</th>
                <th>Description</th>
                <th>Type</th>
                <th>Parameters</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """


# ══════════════════════════════════════════════════════════════════
#  PLATFORM INFO
# ══════════════════════════════════════════════════════════════════

PLATFORM_INFO = {
    "microbit": {
        "label": "Micro:bit MakeCode (STS)",
        "icon": "📟",
        "copy_instructions": "Copy this code into MakeCode (makecode.microbit.org) and flash your Micro:bit V2.",
        "open_label": "🔗 Open MakeCode",
        "open_url": "https://makecode.microbit.org/",
        "language": "typescript",
    },
    "acecode": {
        "label": "ACECode (Arduino IDE)",
        "icon": "🕷️",
        "copy_instructions": "Open this code in Arduino IDE with the ACB_Spider_ESP8266 library installed, select your board, and flash via USB.",
        "open_label": "🔗 Open Arduino IDE",
        "open_url": "https://www.arduino.cc/en/software",
        "language": "c",
    },
}


# ══════════════════════════════════════════════════════════════════
#  SELECTED ROBOT STATE
# ══════════════════════════════════════════════════════════════════

available_robots = discover_robots()
# Restore saved robot if it still exists, otherwise use first available
selected_robot: str = (
    _saved["robot"] if _saved["robot"] in available_robots
    else (available_robots[0] if available_robots else "")
)

# Pre-load initial robot data
_initial_config = load_robot_config(selected_robot) if selected_robot else {}
_initial_firmware, _initial_filename = load_robot_firmware(selected_robot) if selected_robot else ("", "")
_initial_platform = PLATFORM_INFO.get(
    _initial_config.get("firmware_platform", ""), PLATFORM_INFO.get("microbit")
)

# Mutable state dict so button lambdas always read current values
_firmware_state = {
    "source": _initial_firmware,
    "open_url": _initial_platform["open_url"] if _initial_platform else "",
}

# Build initial system prompt for the selected robot
if selected_robot:
    build_and_set_prompt(selected_robot)

# Auto-configure Gemini if an API key was previously saved
if _saved["api_key"]:
    try:
        gemini.configure(api_key=_saved["api_key"])
        if _saved["model"] in AVAILABLE_MODELS:
            gemini.model_label = _saved["model"]
        if selected_robot:
            build_and_set_prompt(selected_robot)
    except Exception:
        pass  # Key might be stale; user can re-enter


# ══════════════════════════════════════════════════════════════════
#  UI CONSTRUCTION
# ══════════════════════════════════════════════════════════════════

# Theme & custom CSS
ui.add_head_html("""
<style>
  :root {
    --primary: #FF6B35;
    --primary-light: #FF8C5A;
    --secondary: #4ECDC4;
    --secondary-light: #7EDDD6;
    --accent-pink: #FF6B9D;
    --accent-yellow: #FFD93D;
    --accent-purple: #A855F7;
    --bg-main: #FFF8F0;
    --bg-card: #FFFFFF;
    --bg-input: #FFF0E6;
    --text-dark: #2D3436;
    --text-medium: #636E72;
    --text-light: #B2BEC3;
    --danger: #FF4757;
    --success: #2ED573;
    --shadow-soft: 0 4px 20px rgba(255, 107, 53, 0.12);
    --shadow-card: 0 6px 24px rgba(0, 0, 0, 0.06);
    --shadow-hover: 0 8px 32px rgba(255, 107, 53, 0.18);
    --radius-lg: 20px;
    --radius-md: 16px;
    --radius-sm: 12px;
  }

  body {
    background: var(--bg-main) !important;
    color: var(--text-dark) !important;
    font-family: 'Outfit', 'Segoe UI', system-ui, sans-serif !important;
  }

  /* === Tabs === */
  .q-tab-panel { background: var(--bg-main) !important; }
  .q-tab--active { color: var(--primary) !important; font-weight: 700 !important; }
  .q-tabs {
    background: var(--bg-card) !important;
    border-bottom: 3px solid var(--accent-yellow) !important;
    border-radius: var(--radius-md) var(--radius-md) 0 0;
  }
  .q-tab {
    color: var(--text-medium) !important;
    font-weight: 600;
    font-size: 1rem !important;
    min-height: 56px !important;
    transition: all 0.25s ease;
  }
  .q-tab:hover { color: var(--primary) !important; }
  .q-tab__indicator { background: var(--primary) !important; height: 4px !important; border-radius: 2px; }

  /* === Chat messages === */
  .chat-msg {
    padding: 14px 18px;
    border-radius: var(--radius-md);
    margin: 6px 0;
    max-width: 85%;
    line-height: 1.6;
    font-size: 1.05rem;
    animation: pop-in 0.3s ease;
  }
  @keyframes pop-in {
    0% { opacity: 0; transform: scale(0.9) translateY(8px); }
    100% { opacity: 1; transform: scale(1) translateY(0); }
  }
  .chat-user {
    background: linear-gradient(135deg, var(--primary) 0%, var(--accent-pink) 100%);
    color: white;
    margin-left: auto;
    border-bottom-right-radius: 4px;
    box-shadow: 0 3px 12px rgba(255, 107, 53, 0.25);
  }
  .chat-assistant {
    background: var(--bg-card);
    color: var(--text-dark);
    border: 2px solid var(--secondary-light);
    border-bottom-left-radius: 4px;
    box-shadow: var(--shadow-card);
  }
  .chat-time {
    font-size: 0.72rem;
    color: var(--text-light);
    margin-top: 4px;
  }

  /* === Code viewer === */
  .code-viewer {
    background: #2D2B55 !important;
    border: 3px solid var(--accent-purple);
    border-radius: var(--radius-md);
    padding: 18px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.88rem;
    white-space: pre-wrap;
    color: #A9FFA7;
    overflow-y: auto;
    max-height: 320px;
    box-shadow: 0 4px 16px rgba(168, 85, 247, 0.15);
  }

  /* === Stop button === */
  .stop-btn {
    background: linear-gradient(135deg, #CC0000, #AA0000) !important;
    color: white !important;
    font-weight: 800 !important;
    font-size: 1.1rem !important;
    border-radius: var(--radius-lg) !important;
    text-transform: uppercase;
    letter-spacing: 1px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25), 0 0 0 3px rgba(255, 255, 255, 0.5);
    transition: all 0.2s ease;
    min-width: 120px !important;
    padding: 8px 24px !important;
    border: 3px solid rgba(255, 255, 255, 0.6) !important;
  }
  .stop-btn:hover {
    box-shadow: 0 8px 32px rgba(255, 71, 87, 0.55);
    transform: translateY(-2px) scale(1.05);
  }
  .stop-btn:active {
    transform: scale(0.95);
  }

  /* === Fun buttons === */
  .fun-btn {
    border-radius: var(--radius-sm) !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    padding: 8px 20px !important;
    transition: all 0.2s ease !important;
    text-transform: none !important;
    letter-spacing: 0.3px;
  }
  .fun-btn:hover {
    transform: translateY(-2px) scale(1.03);
  }
  .fun-btn:active {
    transform: scale(0.97);
  }
  .fun-btn-primary {
    background: linear-gradient(135deg, var(--primary), var(--primary-light)) !important;
    color: white !important;
    box-shadow: 0 4px 14px rgba(255, 107, 53, 0.3);
  }
  .fun-btn-secondary {
    background: linear-gradient(135deg, var(--secondary), var(--secondary-light)) !important;
    color: white !important;
    box-shadow: 0 4px 14px rgba(78, 205, 196, 0.3);
  }
  .fun-btn-purple {
    background: linear-gradient(135deg, var(--accent-purple), #C084FC) !important;
    color: white !important;
    box-shadow: 0 4px 14px rgba(168, 85, 247, 0.3);
  }
  .fun-btn-ghost {
    background: var(--bg-input) !important;
    color: var(--text-medium) !important;
    box-shadow: var(--shadow-card);
  }

  /* === Settings card === */
  .settings-card {
    background: var(--bg-card);
    border: 2px solid #F0E6D8;
    border-radius: var(--radius-lg);
    padding: 24px;
    box-shadow: var(--shadow-card);
    transition: box-shadow 0.2s ease;
  }
  .settings-card:hover {
    box-shadow: var(--shadow-hover);
  }

  /* === Protocol table === */
  .protocol-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0 6px;
    font-size: 0.95rem;
  }
  .protocol-table th {
    background: linear-gradient(135deg, var(--primary), var(--accent-pink));
    color: white;
    padding: 14px 18px;
    text-align: left;
    font-weight: 700;
    font-size: 0.9rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .protocol-table th:first-child { border-radius: var(--radius-sm) 0 0 var(--radius-sm); }
  .protocol-table th:last-child { border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }
  .protocol-table td {
    padding: 12px 18px;
    background: var(--bg-card);
    color: var(--text-dark);
    border-top: 1px solid #F0E6D8;
    border-bottom: 1px solid #F0E6D8;
  }
  .protocol-table tr td:first-child {
    border-left: 1px solid #F0E6D8;
    border-radius: var(--radius-sm) 0 0 var(--radius-sm);
  }
  .protocol-table tr td:last-child {
    border-right: 1px solid #F0E6D8;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  }
  .protocol-table tr:hover td {
    background: var(--bg-input);
    transform: scale(1.005);
  }
  .protocol-table code {
    background: #2D2B55;
    color: #A9FFA7;
    padding: 3px 8px;
    border-radius: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
  }

  /* === Command type badges === */
  .cmd-type {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .cmd-setter {
    background: linear-gradient(135deg, rgba(168, 85, 247, 0.15), rgba(192, 132, 252, 0.15));
    color: #7C3AED;
    border: 2px solid rgba(168, 85, 247, 0.3);
  }
  .cmd-getter {
    background: linear-gradient(135deg, rgba(78, 205, 196, 0.15), rgba(126, 221, 214, 0.15));
    color: #0D946E;
    border: 2px solid rgba(78, 205, 196, 0.4);
  }

  /* === Connection badge === */
  .conn-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 16px;
    border-radius: 24px;
    font-size: 0.85rem;
    font-weight: 700;
  }
  .conn-online {
    background: rgba(255, 255, 255, 0.92);
    color: #0D9E3F;
    border: 2px solid rgba(46, 213, 115, 0.5);
    animation: pulse-online 2s ease-in-out infinite;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  }
  @keyframes pulse-online {
    0%, 100% { box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); }
    50% { box-shadow: 0 2px 8px rgba(46, 213, 115, 0.3); }
  }
  .conn-offline {
    background: rgba(255, 255, 255, 0.92);
    color: var(--danger);
    border: 2px solid rgba(255, 71, 87, 0.4);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  }

  /* === Robot badge === */
  .robot-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 16px;
    border-radius: 24px;
    font-size: 0.9rem;
    font-weight: 700;
    background: rgba(255, 255, 255, 0.92);
    color: var(--primary);
    border: 2px solid rgba(255, 107, 53, 0.4);
    text-transform: capitalize;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  }

  /* === Status bar === */
  .status-bar {
    background: var(--bg-card);
    border-top: 3px solid var(--accent-yellow);
    padding: 10px 24px;
    font-size: 0.85rem;
    color: var(--text-medium);
  }

  /* === Header === */
  .app-header {
    background: linear-gradient(135deg, var(--primary) 0%, var(--accent-pink) 50%, var(--accent-purple) 100%);
    padding: 14px 28px;
    box-shadow: 0 4px 20px rgba(255, 107, 53, 0.25);
  }
  .app-title {
    font-size: 1.5rem;
    font-weight: 800;
    color: white;
    text-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    letter-spacing: -0.3px;
  }
  .app-subtitle {
    color: rgba(255, 255, 255, 0.85);
    font-size: 0.9rem;
    font-weight: 500;
  }

  /* === Section titles === */
  .section-title {
    font-weight: 800;
    font-size: 1.15rem;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  /* === Input styling === */
  .nicegui-input .q-field__control {
    background: var(--bg-input) !important;
    border-radius: var(--radius-sm) !important;
    border: 2px solid #F0E6D8 !important;
  }
  .nicegui-input .q-field__native,
  .nicegui-input .q-field__label {
    color: var(--text-dark) !important;
  }
  .nicegui-input .q-field--focused .q-field__control {
    border-color: var(--primary) !important;
  }
  .nicegui-select .q-field__control {
    background: var(--bg-input) !important;
    border-radius: var(--radius-sm) !important;
    border: 2px solid #F0E6D8 !important;
  }

  /* === Bouncy wiggle animation for mascot === */
  @keyframes bounce-wiggle {
    0%, 100% { transform: rotate(0deg) scale(1); }
    25% { transform: rotate(-5deg) scale(1.1); }
    50% { transform: rotate(5deg) scale(1.05); }
    75% { transform: rotate(-3deg) scale(1.08); }
  }
  .mascot-img {
    display: inline-block;
    width: 64px;
    height: 64px;
    object-fit: contain;
    animation: bounce-wiggle 3s ease-in-out infinite;
    cursor: default;
    filter: drop-shadow(0 2px 6px rgba(0,0,0,0.20));
  }

  /* === Quasar overrides for light mode === */
  .q-dark { background: var(--bg-main) !important; }
  .q-field--dark .q-field__control { background: var(--bg-input) !important; }
  .q-field--dark .q-field__native { color: var(--text-dark) !important; }

  /* === Voice / Mic button === */
  .mic-btn {
    width: 44px !important;
    height: 44px !important;
    min-width: 44px !important;
    border-radius: 50% !important;
    transition: all 0.25s ease !important;
    color: var(--primary) !important;
    font-size: 1.25rem !important;
  }
  .mic-btn:hover {
    background: var(--bg-input) !important;
    transform: scale(1.1);
  }
  .mic-btn-recording {
    color: white !important;
    background: var(--danger) !important;
    box-shadow: 0 0 0 0 rgba(255, 71, 87, 0.6);
    animation: mic-pulse 1.2s ease-in-out infinite;
  }
  .mic-btn-recording:hover {
    background: #e8414f !important;
  }
  @keyframes mic-pulse {
    0% { box-shadow: 0 0 0 0 rgba(255, 71, 87, 0.6); }
    70% { box-shadow: 0 0 0 12px rgba(255, 71, 87, 0); }
    100% { box-shadow: 0 0 0 0 rgba(255, 71, 87, 0); }
  }
  .voice-status {
    font-size: 0.8rem;
    color: var(--danger);
    font-weight: 600;
    min-height: 1.2em;
    animation: fade-in-out 1.5s ease-in-out infinite;
  }
  @keyframes fade-in-out {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  /* === Robot Face === */
  .robot-face-container {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    min-height: 380px;
    position: relative;
    overflow: hidden;
  }
  .robot-face-wrapper {
    position: relative;
    animation: face-float 4s ease-in-out infinite;
  }
  @keyframes face-float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-8px); }
  }

  /* Glow ring behind face */
  .face-glow {
    position: absolute;
    top: 50%; left: 50%;
    width: 280px; height: 280px;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    background: radial-gradient(circle, rgba(78,205,196,0.15) 0%, transparent 70%);
    transition: all 0.5s ease;
    pointer-events: none;
  }

  /* Eye blink */
  .robot-eye-pupil {
    animation: blink 4s ease-in-out infinite;
  }
  @keyframes blink {
    0%, 42%, 44%, 100% { transform: scaleY(1); }
    43% { transform: scaleY(0.08); }
  }

  /* Mouth idle */
  .robot-mouth {
    transition: all 0.4s ease;
  }

  /* === Listening State === */
  .robot-face-listening .face-glow {
    width: 340px; height: 340px;
    background: radial-gradient(circle, rgba(255,107,53,0.3) 0%, rgba(255,71,87,0.1) 50%, transparent 70%);
    animation: glow-pulse 1.2s ease-in-out infinite;
  }
  @keyframes glow-pulse {
    0%, 100% { opacity: 0.6; transform: translate(-50%, -50%) scale(1); }
    50% { opacity: 1; transform: translate(-50%, -50%) scale(1.15); }
  }
  .robot-face-listening .robot-eye-pupil {
    animation: eyes-widen 0.4s ease forwards;
  }
  @keyframes eyes-widen {
    0% { r: 10; }
    100% { r: 14; }
  }
  .robot-face-listening .robot-eye-white {
    animation: eye-pop 0.4s ease forwards;
  }
  @keyframes eye-pop {
    0% { r: 22; }
    100% { r: 26; }
  }
  .robot-face-listening .robot-mouth {
    rx: 18;
    ry: 8;
  }
  .robot-face-listening .sound-wave {
    opacity: 1;
    animation: wave-ripple 1s ease-in-out infinite;
  }
  .sound-wave {
    opacity: 0;
    transition: opacity 0.3s ease;
  }
  @keyframes wave-ripple {
    0% { r: 120; opacity: 0.6; stroke-width: 3; }
    100% { r: 160; opacity: 0; stroke-width: 0.5; }
  }
  .robot-face-listening .sound-wave:nth-child(2) {
    animation-delay: 0.3s;
  }
  .robot-face-listening .sound-wave:nth-child(3) {
    animation-delay: 0.6s;
  }
  .robot-face-listening .robot-face-wrapper {
    animation: face-float 2s ease-in-out infinite;
  }

  /* Ear antenna glow when listening */
  .robot-face-listening .antenna-tip {
    animation: antenna-blink 0.6s ease-in-out infinite alternate;
  }
  @keyframes antenna-blink {
    0% { fill: #FF6B35; filter: drop-shadow(0 0 4px #FF6B35); }
    100% { fill: #FFD93D; filter: drop-shadow(0 0 10px #FFD93D); }
  }

  /* === Thinking State === */
  .robot-face-thinking .face-glow {
    width: 310px; height: 310px;
    background: radial-gradient(circle, rgba(168,85,247,0.25) 0%, rgba(192,132,252,0.1) 50%, transparent 70%);
    animation: glow-think 2s ease-in-out infinite;
  }
  @keyframes glow-think {
    0%, 100% { opacity: 0.5; }
    50% { opacity: 0.9; }
  }
  .robot-face-thinking .robot-eye-pupil {
    animation: think-look 2s ease-in-out infinite;
  }
  @keyframes think-look {
    0%, 100% { transform: translateX(0); }
    25% { transform: translateX(6px); }
    50% { transform: translateX(0); }
    75% { transform: translateX(-6px); }
  }
  .robot-face-thinking .thinking-dots {
    opacity: 1;
  }
  .thinking-dots {
    opacity: 0;
    transition: opacity 0.3s ease;
  }
  .thinking-dot {
    animation: dot-bounce 1.4s ease-in-out infinite;
  }
  .thinking-dot:nth-child(2) { animation-delay: 0.2s; }
  .thinking-dot:nth-child(3) { animation-delay: 0.4s; }
  @keyframes dot-bounce {
    0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
    40% { transform: translateY(-8px); opacity: 1; }
  }
  .robot-face-thinking .gear-icon {
    opacity: 0.7;
    animation: spin-gear 3s linear infinite;
  }
  .gear-icon {
    opacity: 0;
    transition: opacity 0.4s ease;
  }
  @keyframes spin-gear {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
  .robot-face-thinking .robot-face-wrapper {
    animation: none;
  }

  /* Face label */
  .face-state-label {
    text-align: center;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-medium);
    margin-top: 8px;
    min-height: 1.4em;
    transition: all 0.3s ease;
  }
  .robot-face-listening .face-state-label {
    color: var(--danger);
    animation: fade-in-out 1.5s ease-in-out infinite;
  }
  .robot-face-thinking .face-state-label {
    color: var(--accent-purple);
    animation: fade-in-out 2s ease-in-out infinite;
  }

  /* === Collapsible code viewer === */
  .code-expansion .q-expansion-item__container {
    background: var(--bg-card);
    border: 2px solid var(--accent-purple);
    border-radius: var(--radius-md) !important;
    overflow: hidden;
  }
  .code-expansion .q-item {
    background: linear-gradient(135deg, rgba(168,85,247,0.08), rgba(192,132,252,0.05));
    min-height: 44px !important;
    padding: 6px 16px !important;
    border-radius: var(--radius-md) var(--radius-md) 0 0;
  }
  .code-expansion .q-item__label {
    font-weight: 700;
    color: var(--accent-purple);
    font-size: 0.95rem;
  }
  .code-expansion .q-expansion-item__content {
    padding: 0 !important;
  }

</style>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
""")

# ── Voice input JavaScript (Web Speech API) ──────────────────────
ui.add_head_html("""
<script>
let _voiceRecognition = null;
let _voiceIsListening = false;

function setRobotFaceState(state) {
    const container = document.getElementById('robot-face-outer');
    if (!container) return;
    container.classList.remove('robot-face-idle', 'robot-face-listening', 'robot-face-thinking');
    container.classList.add('robot-face-' + state);
    const label = document.getElementById('face-state-text');
    if (label) {
        if (state === 'listening') label.textContent = '🎙️ Listening…';
        else if (state === 'thinking') label.textContent = '🧠 Thinking…';
        else label.textContent = '😊 Ready to chat!';
    }
}

function toggleVoiceInput() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        window.__voiceNotSupported = true;
        return 'unsupported';
    }

    if (_voiceIsListening && _voiceRecognition) {
        _voiceRecognition.stop();
        return 'stopped';
    }

    _voiceRecognition = new SpeechRecognition();
    _voiceRecognition.lang = 'en-US';
    _voiceRecognition.interimResults = false;
    _voiceRecognition.maxAlternatives = 1;
    _voiceRecognition.continuous = false;

    _voiceRecognition.onstart = function() {
        _voiceIsListening = true;
        const btn = document.getElementById('mic-toggle-btn');
        if (btn) btn.classList.add('mic-btn-recording');
        const status = document.getElementById('voice-status-label');
        if (status) { status.textContent = '🎙️ Listening…'; status.style.display = 'block'; }
        setRobotFaceState('listening');
    };

    _voiceRecognition.onresult = function(event) {
        const transcript = event.results[0][0].transcript;
        const inputEl = document.querySelector('#voice-chat-input input, #voice-chat-input textarea');
        if (inputEl) {
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(inputEl, transcript);
            inputEl.dispatchEvent(new Event('input', { bubbles: true }));
            setTimeout(() => {
                inputEl.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
            }, 150);
        }
    };

    _voiceRecognition.onerror = function(event) {
        console.warn('Speech recognition error:', event.error);
        _voiceIsListening = false;
        const btn = document.getElementById('mic-toggle-btn');
        if (btn) btn.classList.remove('mic-btn-recording');
        const status = document.getElementById('voice-status-label');
        if (status) { status.textContent = ''; status.style.display = 'none'; }
        setRobotFaceState('idle');
    };

    _voiceRecognition.onend = function() {
        _voiceIsListening = false;
        const btn = document.getElementById('mic-toggle-btn');
        if (btn) btn.classList.remove('mic-btn-recording');
        const status = document.getElementById('voice-status-label');
        if (status) { status.textContent = ''; status.style.display = 'none'; }
        // Don't reset to idle here — send_chat_message will set thinking then idle
    };

    _voiceRecognition.start();
    return 'started';
}
</script>
""")


# ── Header (always visible) ──────────────────────────────────────
with ui.row().classes("app-header w-full items-center justify-between"):
    with ui.row().classes("items-center gap-3"):
        ui.html(f'<img src="{LOGO_URL}" class="mascot-img" alt="Robot Logo">')
        with ui.column().classes("gap-0"):
            ui.html('<span class="app-title">Robot Command Center!</span>')
            ui.html('<span class="app-subtitle">Miraloma Robotics</span>')

    with ui.row().classes("items-center gap-3"):
        robot_badge = ui.html(
            f'<span class="robot-badge">🤖 {selected_robot.capitalize() if selected_robot else "No Robot"}</span>'
        )
        connection_badge = ui.html(
            '<span class="conn-badge conn-offline">😴 Robot is sleeping</span>'
        )
        stop_button = ui.button(
            "🛑 STOP",
            on_click=lambda: handle_emergency_stop(),
        ).classes("stop-btn").props('flat no-caps')


# ── Tabs ──────────────────────────────────────────────────────────
with ui.tabs().classes("w-full") as tabs:
    tab_workspace = ui.tab("Play", icon="sports_esports")
    tab_firmware = ui.tab("Robot Code", icon="code")
    tab_protocol = ui.tab("Command Book", icon="auto_stories")
    tab_settings = ui.tab("Setup", icon="tune")


with ui.tab_panels(tabs, value=tab_workspace).classes("w-full flex-grow"):

    # ══════════════════════════════════════════════════════════════
    #  TAB 1: WORKSPACE
    # ══════════════════════════════════════════════════════════════
    with ui.tab_panel(tab_workspace):
        with ui.column().classes("w-full gap-3"):
            # ── Top row: Chat + Robot Face ──────────────────────
            with ui.row().classes("w-full gap-4").style("min-height: 460px;"):

                # ── Chat column ───────────────────────────────────
                with ui.column().classes("flex-1"):
                    ui.html(
                        '<div class="section-title" style="color: var(--primary);">'
                        '💬 Talk to Your Robot!</div>'
                    )
                    chat_container = ui.column().classes(
                        "w-full flex-grow gap-1"
                    ).style(
                        "overflow-y: auto; max-height: 400px; padding: 12px; "
                        "background: var(--bg-card); border-radius: var(--radius-lg); "
                        "border: 2px solid #F0E6D8; box-shadow: var(--shadow-card);"
                    )

                    # Welcome message
                    with chat_container:
                        ui.html(
                            '<div class="chat-msg chat-assistant">'
                            "👋 <b>Hey there, Robot Commander!</b><br>"
                            "Pick your robot in <b>⚙️ Setup</b>, plug it in, then tell me what cool things to do!<br>"
                            '<span class="chat-time">Robot Brain</span></div>'
                        )

                    # Input row
                    with ui.row().classes("w-full items-center gap-2 mt-2"):
                        chat_input = ui.input(
                            placeholder="What should the robot do? 🤔"
                        ).classes("nicegui-input flex-grow").props(
                            'outlined dense id=voice-chat-input'
                        ).on("keydown.enter", lambda: send_chat_message())

                        # Microphone button (Web Speech API)
                        mic_button = ui.button(
                            icon="mic",
                            on_click=lambda: handle_voice_toggle(),
                        ).props("flat round").classes("mic-btn").props(
                            'id=mic-toggle-btn'
                        )

                        ui.button(
                            icon="send",
                            on_click=lambda: send_chat_message(),
                        ).props("flat round").style("color: var(--primary); font-size: 1.2rem;")

                    # Voice status indicator
                    voice_status = ui.html(
                        '<span id="voice-status-label" class="voice-status" style="display: none;"></span>'
                    )

                # ── Robot Face column ─────────────────────────────
                with ui.column().classes("flex-1 items-center justify-center"):
                    robot_face_html = ui.html('''
                    <div id="robot-face-outer" class="robot-face-idle">
                      <div class="robot-face-container">
                        <div class="face-glow"></div>
                        <div class="robot-face-wrapper">
                          <svg viewBox="0 0 260 280" width="280" height="300" xmlns="http://www.w3.org/2000/svg">
                            <!-- Sound waves (visible when listening) -->
                            <circle class="sound-wave" cx="130" cy="120" r="130" fill="none" stroke="#FF6B35" stroke-width="2"/>
                            <circle class="sound-wave" cx="130" cy="120" r="130" fill="none" stroke="#FF6B35" stroke-width="2"/>
                            <circle class="sound-wave" cx="130" cy="120" r="130" fill="none" stroke="#FF6B35" stroke-width="2"/>

                            <!-- Antenna -->
                            <line x1="130" y1="28" x2="130" y2="8" stroke="#B0B8C4" stroke-width="4" stroke-linecap="round"/>
                            <circle class="antenna-tip" cx="130" cy="6" r="6" fill="#FF6B35"/>

                            <!-- Head -->
                            <rect x="40" y="28" width="180" height="160" rx="36" ry="36"
                                  fill="url(#headGrad)" stroke="#B0B8C4" stroke-width="3"/>

                            <!-- Gradients -->
                            <defs>
                              <linearGradient id="headGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                                <stop offset="0%" style="stop-color:#E8EDF2"/>
                                <stop offset="100%" style="stop-color:#CDD5DE"/>
                              </linearGradient>
                              <radialGradient id="eyeGlowL">
                                <stop offset="0%" style="stop-color:#4ECDC4; stop-opacity:0.3"/>
                                <stop offset="100%" style="stop-color:#4ECDC4; stop-opacity:0"/>
                              </radialGradient>
                              <radialGradient id="eyeGlowR">
                                <stop offset="0%" style="stop-color:#FF6B9D; stop-opacity:0.3"/>
                                <stop offset="100%" style="stop-color:#FF6B9D; stop-opacity:0"/>
                              </radialGradient>
                            </defs>

                            <!-- Eye glow -->
                            <circle cx="90" cy="100" r="32" fill="url(#eyeGlowL)"/>
                            <circle cx="170" cy="100" r="32" fill="url(#eyeGlowR)"/>

                            <!-- Eyes whites -->
                            <circle class="robot-eye-white" cx="90" cy="100" r="22" fill="white"
                                    stroke="#B0B8C4" stroke-width="2"/>
                            <circle class="robot-eye-white" cx="170" cy="100" r="22" fill="white"
                                    stroke="#B0B8C4" stroke-width="2"/>

                            <!-- Pupils -->
                            <circle class="robot-eye-pupil" cx="90" cy="100" r="10" fill="#2D3436"/>
                            <circle class="robot-eye-pupil" cx="170" cy="100" r="10" fill="#2D3436"/>

                            <!-- Pupil highlights -->
                            <circle cx="95" cy="95" r="3.5" fill="white" opacity="0.9"/>
                            <circle cx="175" cy="95" r="3.5" fill="white" opacity="0.9"/>

                            <!-- Cheek blush -->
                            <ellipse cx="65" cy="128" rx="14" ry="8" fill="#FFB8C6" opacity="0.45"/>
                            <ellipse cx="195" cy="128" rx="14" ry="8" fill="#FFB8C6" opacity="0.45"/>

                            <!-- Mouth (smile) -->
                            <ellipse class="robot-mouth" cx="130" cy="148" rx="22" ry="10"
                                     fill="#FF6B9D" opacity="0.7"/>
                            <ellipse cx="130" cy="146" rx="18" ry="5"
                                     fill="white" opacity="0.25"/>

                            <!-- Ears -->
                            <rect x="20" y="78" width="16" height="44" rx="8" fill="#B0B8C4" stroke="#9CA8B4" stroke-width="1.5"/>
                            <rect x="224" y="78" width="16" height="44" rx="8" fill="#B0B8C4" stroke="#9CA8B4" stroke-width="1.5"/>

                            <!-- Neck -->
                            <rect x="110" y="188" width="40" height="16" rx="4" fill="#CDD5DE" stroke="#B0B8C4" stroke-width="1.5"/>

                            <!-- Body hint -->
                            <rect x="70" y="204" width="120" height="56" rx="20" ry="20"
                                  fill="url(#headGrad)" stroke="#B0B8C4" stroke-width="2.5"/>
                            <!-- Body details -->
                            <circle cx="110" cy="228" r="5" fill="#4ECDC4" opacity="0.6"/>
                            <circle cx="130" cy="228" r="5" fill="#FF6B35" opacity="0.6"/>
                            <circle cx="150" cy="228" r="5" fill="#A855F7" opacity="0.6"/>

                            <!-- Thinking dots (visible when thinking) -->
                            <g class="thinking-dots" transform="translate(130, 270)">
                              <circle class="thinking-dot" cx="-16" cy="0" r="5" fill="#A855F7"/>
                              <circle class="thinking-dot" cx="0" cy="0" r="5" fill="#A855F7"/>
                              <circle class="thinking-dot" cx="16" cy="0" r="5" fill="#A855F7"/>
                            </g>

                            <!-- Gear icon (visible when thinking) -->
                            <g class="gear-icon" transform="translate(210, 40)">
                              <circle cx="0" cy="0" r="12" fill="none" stroke="#A855F7" stroke-width="3"/>
                              <line x1="0" y1="-16" x2="0" y2="16" stroke="#A855F7" stroke-width="3" stroke-linecap="round"/>
                              <line x1="-16" y1="0" x2="16" y2="0" stroke="#A855F7" stroke-width="3" stroke-linecap="round"/>
                              <line x1="-11" y1="-11" x2="11" y2="11" stroke="#A855F7" stroke-width="3" stroke-linecap="round"/>
                              <line x1="11" y1="-11" x2="-11" y2="11" stroke="#A855F7" stroke-width="3" stroke-linecap="round"/>
                            </g>
                          </svg>
                        </div>
                      </div>
                      <div id="face-state-text" class="face-state-label">😊 Ready to chat!</div>
                    </div>
                    ''')

            # ── Action buttons (always visible) ─────────────────────
            with ui.row().classes("gap-2 w-full items-center"):
                ui.button(
                    "🚀 Go!", on_click=lambda: execute_code(),
                ).classes("fun-btn fun-btn-primary").props("flat no-caps")
                ui.button(
                    "🧹 Start Over", on_click=lambda: clear_code(),
                ).classes("fun-btn fun-btn-ghost").props("flat no-caps")

            # ── Collapsible code viewer ───────────────────────────
            with ui.expansion(
                "🧠 Navigation Script", icon="code",
            ).classes("w-full code-expansion").props("dense") as code_expansion:
                code_display = ui.html(
                    f'<pre class="code-viewer" style="margin: 0; border: none; border-radius: 0 0 var(--radius-md) var(--radius-md);">{current_code}</pre>'
                )



    # ══════════════════════════════════════════════════════════════
    #  TAB 2: FIRMWARE
    # ══════════════════════════════════════════════════════════════
    with ui.tab_panel(tab_firmware):
        firmware_container = ui.column().classes("w-full gap-3")
        with firmware_container:
            firmware_title = ui.html(
                f'<div class="section-title" style="color: var(--primary);">'
                f'{_initial_platform["icon"]} {_initial_platform["label"]} Code</div>'
            )
            firmware_instructions = ui.label(
                _initial_platform["copy_instructions"]
            ).style("color: var(--text-medium); font-size: 0.95rem;")

            with ui.row().classes("gap-2"):
                firmware_copy_btn = ui.button(
                    "📋 Copy Code",
                    on_click=lambda: ui.run_javascript(
                        f"navigator.clipboard.writeText({json.dumps(_firmware_state['source'])})"
                        ".then(() => {{ }})"
                    ),
                ).classes("fun-btn fun-btn-secondary").props("flat no-caps")
                firmware_open_btn = ui.button(
                    _initial_platform["open_label"],
                    on_click=lambda: ui.run_javascript(
                        f"window.open('{_firmware_state['open_url']}', '_blank')"
                    ),
                ).classes("fun-btn fun-btn-purple").props("flat no-caps").style("color: white !important;")

            firmware_code_display = ui.html(
                f'<pre class="code-viewer" style="max-height: 500px;">'
                f'{_escape_html(_initial_firmware)}</pre>'
            )
            firmware_filename_label = ui.label(
                f"📄 {_initial_filename}"
            ).style("color: var(--text-medium); font-size: 0.85rem; margin-top: 4px;")


    # ══════════════════════════════════════════════════════════════
    #  TAB 3: PROTOCOL DOCS
    # ══════════════════════════════════════════════════════════════
    with ui.tab_panel(tab_protocol):
        protocol_container = ui.column().classes("w-full gap-3")
        with protocol_container:
            protocol_title = ui.html(
                '<div class="section-title" style="color: var(--primary);">'
                '📖 Robot Command Book</div>'
            )
            protocol_meta = ui.label(
                f"Robot: {selected_robot.capitalize()} · "
                f"Platform: {_initial_config.get('firmware_platform', '?')} · "
                f"Speed: {_initial_config.get('baud_rate', '?')}"
            ).style("color: var(--text-medium); font-size: 0.95rem; margin-bottom: 12px;")

            if _initial_config:
                protocol_table_html = ui.html(_build_protocol_table(_initial_config))
            else:
                protocol_table_html = ui.html(
                    '<span style="color: var(--danger); font-size: 1.1rem;">⚠️ No commands found for this robot.</span>'
                )


    # ══════════════════════════════════════════════════════════════
    #  TAB 4: SETTINGS
    # ══════════════════════════════════════════════════════════════
    with ui.tab_panel(tab_settings):
        with ui.column().classes("w-full gap-6").style("max-width: 600px;"):

            # Robot type section
            ui.html(
                '<div class="section-title" style="color: var(--primary);">'
                '🤖 Pick Your Robot!</div>'
            )
            with ui.column().classes("settings-card gap-4"):
                ui.label(
                    "Choose which robot you want to talk to! "
                    "New robots show up automatically."
                ).style("color: var(--text-medium); font-size: 0.95rem;")

                robot_options = {r: r.capitalize() for r in available_robots}
                robot_select = ui.select(
                    options=robot_options,
                    label="Which robot?",
                    value=selected_robot,
                    on_change=lambda e: handle_robot_change(e.value),
                ).classes("nicegui-select w-full")

                robot_platform_label = ui.label(
                    f"Type: {_initial_config.get('firmware_platform', '').upper()}"
                ).style("color: var(--text-medium); font-size: 0.9rem;")

            # Serial section
            ui.html(
                '<div class="section-title" style="color: var(--secondary);">'
                '🔌 Connect Your Robot!</div>'
            )
            with ui.column().classes("settings-card gap-4"):
                ports = robot.list_ports()
                port_select = ui.select(
                    options=ports if ports else ["(no robot found)"],
                    label="USB Port",
                    value=ports[0] if ports else "(no robot found)",
                ).classes("nicegui-select w-full")

                _saved_baud = _saved["uart_baud"] if _saved["uart_baud"] in [9600, 19200, 38400, 57600, 115200] else 115200
                baud_select = ui.select(
                    options=[9600, 19200, 38400, 57600, 115200],
                    label="Speed",
                    value=_saved_baud,
                ).classes("nicegui-select w-full")

                with ui.row().classes("gap-2"):
                    ui.button(
                        "🔌 Plug In!",
                        on_click=lambda: handle_connect(),
                    ).classes("fun-btn fun-btn-secondary").props("flat no-caps")
                    ui.button(
                        "🚫 Unplug",
                        on_click=lambda: handle_disconnect(),
                    ).classes("fun-btn fun-btn-ghost").props("flat no-caps")
                    ui.button(
                        "🔄 Look Again",
                        on_click=lambda: refresh_ports(),
                    ).classes("fun-btn fun-btn-ghost").props("flat no-caps")

                serial_status = ui.label("Not connected yet").style(
                    "color: var(--text-medium); font-size: 0.9rem;"
                )

            # Gemini section
            ui.html(
                '<div class="section-title" style="color: var(--accent-purple);">'
                '🧠 AI Brain (Google Gemini)</div>'
            )
            with ui.column().classes("settings-card gap-4"):
                ui.label(
                    "Connect to Google Gemini to give your robot AI superpowers! "
                    "You need an API key from Google AI Studio."
                ).style("color: var(--text-medium); font-size: 0.95rem;")

                api_key_input = ui.input(
                    label="Gemini API Key",
                    placeholder="Paste your API key here (starts with AIza…)",
                    value=_saved["api_key"],
                    password=True,
                    password_toggle_button=True,
                ).classes("nicegui-input w-full")

                model_options = {label: label for label in gemini.available_model_labels()}
                _saved_model = _saved["model"] if _saved["model"] in model_options else DEFAULT_MODEL_LABEL
                model_select = ui.select(
                    options=model_options,
                    label="AI Model",
                    value=_saved_model,
                    on_change=lambda e: handle_model_change(e.value),
                ).classes("nicegui-select w-full")

                with ui.row().classes("gap-2"):
                    ui.button(
                        "🚀 Save & Test",
                        on_click=lambda: save_api_key(),
                    ).classes("fun-btn fun-btn-purple").props("flat no-caps").style("color: white !important;")

                    ui.button(
                        "🔗 Get API Key",
                        on_click=lambda: ui.run_javascript(
                            "window.open('https://aistudio.google.com/apikey', '_blank')"
                        ),
                    ).classes("fun-btn fun-btn-ghost").props("flat no-caps")

                gemini_status = ui.label(
                    f"✅ AI brain is awake — using {gemini.model_label}" if gemini.is_connected
                    else "AI brain is sleeping (no key yet)"
                ).style("color: var(--text-medium); font-size: 0.9rem;")

            # Calibration section
            ui.html(
                '<div class="section-title" style="color: var(--accent-yellow);">'
                '⚙️ Calibration</div>'
            )
            with ui.column().classes("settings-card gap-4"):
                ui.label(
                    "Fine-tune how the robot moves. "
                    "Adjust these based on your robot's actual speed."
                ).style("color: var(--text-medium); font-size: 0.95rem;")

                cal_speed_input = ui.number(
                    label="Speed (seconds per foot)",
                    value=calibration["speed_seconds_per_foot"],
                    min=0.5, max=30.0, step=0.5,
                    on_change=lambda e: handle_calibration_change("speed_seconds_per_foot", e.value),
                ).classes("nicegui-input w-full")

                cal_motor_input = ui.number(
                    label="Default Motor Speed (0–255)",
                    value=calibration["default_motor_speed"],
                    min=0, max=255, step=10,
                    on_change=lambda e: handle_calibration_change("default_motor_speed", int(e.value)),
                ).classes("nicegui-input w-full")

                cal_status = ui.label(
                    f"📏 {calibration['speed_seconds_per_foot']} sec/foot · "
                    f"🏎️ Motor speed: {calibration['default_motor_speed']}"
                ).style("color: var(--text-medium); font-size: 0.9rem;")



# ── Status Bar ────────────────────────────────────────────────────
with ui.row().classes("status-bar w-full items-center justify-between"):
    ui.label("🤖 Miraloma Robotics v1.1").style("font-size: 0.85rem;")
    status_label = ui.label("✨ Ready to play!").style("font-size: 0.85rem; color: var(--primary); font-weight: 600;")


# ══════════════════════════════════════════════════════════════════
#  HANDLERS
# ══════════════════════════════════════════════════════════════════


def _save_current_settings() -> None:
    """Persist all current settings to disk."""
    save_settings({
        "api_key": api_key_input.value.strip() if gemini.is_connected else _saved.get("api_key", ""),
        "model": model_select.value,
        "speed_seconds_per_foot": calibration["speed_seconds_per_foot"],
        "default_motor_speed": calibration["default_motor_speed"],
        "uart_port": port_select.value if port_select.value != "(no robot found)" else "",
        "uart_baud": baud_select.value,
        "robot": selected_robot,
    })


def handle_robot_change(robot_name: str) -> None:
    """Handle switching to a different robot type."""
    global selected_robot
    selected_robot = robot_name

    config = load_robot_config(robot_name)
    firmware_src, firmware_file = load_robot_firmware(robot_name)
    platform = PLATFORM_INFO.get(
        config.get("firmware_platform", ""), PLATFORM_INFO.get("microbit")
    )

    # Update header badge
    robot_badge.set_content(
        f'<span class="robot-badge">🤖 {robot_name.capitalize()}</span>'
    )

    # Update settings platform label
    robot_platform_label.set_text(
        f"Type: {config.get('firmware_platform', '').upper()}"
    )

    # Update Firmware tab
    firmware_title.set_content(
        f'<div class="section-title" style="color: var(--primary);">'
        f'{platform["icon"]} {platform["label"]} Code</div>'
    )
    firmware_instructions.set_text(platform["copy_instructions"])
    firmware_code_display.set_content(
        f'<pre class="code-viewer" style="max-height: 500px;">'
        f'{_escape_html(firmware_src)}</pre>'
    )
    firmware_filename_label.set_text(f"📄 {firmware_file}")

    # Update mutable state so existing button lambdas read new values
    _firmware_state["source"] = firmware_src
    _firmware_state["open_url"] = platform["open_url"]

    # Update open-IDE button text
    firmware_open_btn.set_text(platform["open_label"])

    # Update Protocol Docs tab
    protocol_meta.set_text(
        f"Robot: {robot_name.capitalize()} · "
        f"Platform: {config.get('firmware_platform', '?')} · "
        f"Speed: {config.get('baud_rate', '?')}"
    )
    if config:
        protocol_table_html.set_content(_build_protocol_table(config))
    else:
        protocol_table_html.set_content(
            '<span style="color: var(--danger); font-size: 1.1rem;">⚠️ No commands found for this robot.</span>'
        )

    # Update baud rate to match robot config
    if config.get("baud_rate"):
        baud_select.value = config["baud_rate"]
        baud_select.update()

    status_label.set_text(f"Switched to {robot_name.capitalize()}! 🎉")
    ui.notify(f"🤖 Now talking to {robot_name.capitalize()}!", type="positive")

    # Rebuild the system prompt for the new robot
    build_and_set_prompt(robot_name)

    # Persist
    _save_current_settings()


def handle_emergency_stop() -> None:
    """Send emergency stop, kill running code, and update UI."""
    # Stop any running navigation code
    stop_execution()
    try:
        robot.stop()
        ui.notify("🛑 Robot stopped!", type="negative", position="top")
    except ConnectionError:
        ui.notify("⚠️ Robot not plugged in — can't stop!", type="warning", position="top")
    status_label.set_text("🛑 STOPPED!")


def handle_connect() -> None:
    """Connect to the selected serial port."""
    port = port_select.value
    baud = baud_select.value
    if not port or port == "(no robot found)":
        ui.notify("Pick a USB port first!", type="warning")
        return
    try:
        robot.connect(port, baud)
        serial_status.set_text(f"✅ Plugged into {port}")
        connection_badge.set_content(
            '<span class="conn-badge conn-online">🚀 Robot is ready!</span>'
        )
        status_label.set_text(f"Robot plugged in! 🎉")
        ui.notify(f"✅ Robot connected!", type="positive")
        _save_current_settings()
    except Exception as e:
        serial_status.set_text(f"Oops! Something went wrong: {e}")
        ui.notify(f"❌ Couldn't connect: {e}", type="negative")


def handle_disconnect() -> None:
    """Disconnect from serial port."""
    stop_execution()
    robot.disconnect()
    serial_status.set_text("Not connected yet")
    connection_badge.set_content(
        '<span class="conn-badge conn-offline">😴 Robot is sleeping</span>'
    )
    status_label.set_text("Robot unplugged")
    ui.notify("Robot unplugged 👋", type="info")


def refresh_ports() -> None:
    """Refresh the list of available serial ports."""
    ports = robot.list_ports()
    port_select.options = ports if ports else ["(no robot found)"]
    port_select.value = ports[0] if ports else "(no robot found)"
    port_select.update()
    ui.notify(f"Found {len(ports)} robot(s)! 🔍", type="info")


async def handle_voice_toggle() -> None:
    """Toggle voice input on/off via browser Web Speech API."""
    result = await ui.run_javascript("toggleVoiceInput()")
    if result == "unsupported":
        ui.notify(
            "🎤 Voice input is not supported in this browser. Try Chrome or Edge!",
            type="warning",
            position="top",
        )

def handle_model_change(label: str) -> None:
    """Handle switching the AI model."""
    gemini.model_label = label
    ui.notify(f"🧠 Switched to {label}", type="info")
    if gemini.is_connected:
        gemini_status.set_text(f"✅ AI brain is awake — using {label}")
    _save_current_settings()


def handle_calibration_change(key: str, value) -> None:
    """Handle calibration parameter change."""
    calibration[key] = value
    cal_status.set_text(
        f"📏 {calibration['speed_seconds_per_foot']} sec/foot · "
        f"🏎️ Motor speed: {calibration['default_motor_speed']}"
    )
    # Rebuild prompt with new calibration
    if selected_robot:
        build_and_set_prompt(selected_robot)
    ui.notify("⚙️ Calibration updated!", type="info")
    _save_current_settings()


async def save_api_key() -> None:
    """Save the Gemini API key and test the connection."""
    key = api_key_input.value.strip()
    if not key:
        ui.notify("Type in your AI key first!", type="warning")
        return

    gemini_status.set_text("⏳ Testing connection…")
    status_label.set_text("🧠 Connecting AI brain…")

    try:
        gemini.configure(api_key=key)
        # Rebuild prompt after configuring (so chat session picks it up)
        if selected_robot:
            build_and_set_prompt(selected_robot)
        test_reply = await gemini.test_connection()
        gemini_status.set_text(
            f"✅ AI brain is awake! Model: {gemini.model_label}"
        )
        status_label.set_text("✨ AI brain activated!")
        ui.notify("🧠 AI brain activated! Connection works.", type="positive")
        # Persist API key only after successful test
        _save_current_settings()
    except Exception as exc:
        error = str(exc)
        gemini_status.set_text(f"❌ Connection failed: {error[:80]}")
        status_label.set_text("⚠️ AI connection failed")
        ui.notify(f"❌ Could not connect: {error[:120]}", type="negative")


async def send_chat_message() -> None:
    """Handle sending a chat message with intent classification."""
    global current_code
    text = chat_input.value.strip()
    if not text:
        return
    chat_input.value = ""

    now = datetime.now().strftime("%H:%M")

    # User message
    with chat_container:
        ui.html(
            f'<div class="chat-msg chat-user">'
            f"{_escape_html(text)}"
            f'<div class="chat-time">{now}</div></div>'
        )

    status_label.set_text("🤖 Robot is thinking…")
    await ui.run_javascript("setRobotFaceState('thinking')")

    # Get AI response
    response = await gemini.send_message(text)

    # Parse and classify
    parsed = GeminiClient.parse_response(response)
    display_text = GeminiClient.clean_message_for_display(response)

    # Assistant message
    with chat_container:
        ui.html(
            f'<div class="chat-msg chat-assistant">'
            f"{_escape_html(display_text)}"
            f'<div class="chat-time">{now}</div></div>'
        )

    # Handle code if present
    if parsed.has_code:
        current_code = parsed.code
        code_display.set_content(
            f'<pre class="code-viewer" style="margin: 0; border: none; '
            f'border-radius: 0 0 var(--radius-md) var(--radius-md);">'
            f'{_escape_html(parsed.code)}</pre>'
        )
        # Auto-expand the code panel
        code_expansion.open()

        if parsed.response_type == ResponseType.ACTION:
            # Auto-execute action commands immediately
            await ui.run_javascript("setRobotFaceState('idle')")
            status_label.set_text("🚀 Running action…")
            await _execute_code_async(parsed.code)
        elif parsed.response_type == ResponseType.NAVIGATION:
            # Wait for Go! button
            await ui.run_javascript("setRobotFaceState('idle')")
            status_label.set_text("📋 Navigation ready — press Go! to start")
            ui.notify(
                "🧭 Navigation script ready! Press 🚀 Go! to start.",
                type="info",
            )
    else:
        await ui.run_javascript("setRobotFaceState('idle')")
        status_label.set_text("✨ Ready to play!")


async def _execute_code_async(code: str) -> None:
    """Execute generated Python code in a background task."""
    global _running_task

    # Stop any currently running code
    stop_execution()

    # Set up the runtime
    nav_runtime.running = True

    async def _run():
        try:
            # Create a namespace with nav_runtime functions
            exec_globals = {
                "send": nav_runtime.send,
                "read": nav_runtime.read,
                "stop": nav_runtime.stop,
                "wait": nav_runtime.wait,
                "is_running": nav_runtime.is_running,
                "__builtins__": __builtins__,
            }
            # Run the code in a thread so it doesn't block the UI
            await asyncio.to_thread(exec, code, exec_globals)
        except Exception as exc:
            ui.notify(f"⚠️ Script error: {exc}", type="negative")
        finally:
            nav_runtime.running = False
            status_label.set_text("✨ Ready to play!")

    _running_task = asyncio.create_task(_run())


def stop_execution() -> None:
    """Stop any running navigation code."""
    global _running_task
    nav_runtime.running = False
    if _running_task and not _running_task.done():
        _running_task.cancel()
    _running_task = None


def execute_code() -> None:
    """Execute the current navigation script (triggered by Go! button)."""
    if "No navigation script" in current_code:
        ui.notify("Tell the robot what to do first! 💬", type="warning")
        return
    status_label.set_text("🚀 Running…")
    asyncio.ensure_future(_execute_code_async(current_code))


def clear_code() -> None:
    """Clear the current navigation script and stop execution."""
    global current_code
    stop_execution()
    try:
        robot.stop()
    except ConnectionError:
        pass
    current_code = "# No navigation script loaded yet."
    code_display.set_content(
        f'<pre class="code-viewer">{current_code}</pre>'
    )
    status_label.set_text("✨ Ready to play!")


# ══════════════════════════════════════════════════════════════════
#  LAUNCH
# ══════════════════════════════════════════════════════════════════
ui.run(
    title="Robot Command Center! — Miraloma Robotics",
    favicon=str(BASE_DIR / 'static' / 'logo.png'),
    host="0.0.0.0",
    port=8080,
    dark=False,
    reload=True,
)

