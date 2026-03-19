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
from datetime import datetime
from pathlib import Path

from nicegui import ui, app

from robot_hal import RobotHAL
from gemini_client import GeminiClient

# ── Globals ───────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
ROBOTS_DIR = BASE_DIR / "robots_firmware"
robot = RobotHAL()
gemini = GeminiClient()

# Chat history: list of {"role": "user"|"assistant", "text": str, "time": str}
chat_history: list[dict] = []
# Currently displayed navigation code
current_code: str = "# No navigation script loaded yet."


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
selected_robot: str = available_robots[0] if available_robots else ""

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
  .mascot {
    display: inline-block;
    font-size: 3rem;
    animation: bounce-wiggle 3s ease-in-out infinite;
    cursor: default;
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

</style>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
""")

# ── Voice input JavaScript (Web Speech API) ──────────────────────
ui.add_head_html("""
<script>
let _voiceRecognition = null;
let _voiceIsListening = false;

function toggleVoiceInput() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        // Browser does not support speech recognition
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
    };

    _voiceRecognition.onresult = function(event) {
        const transcript = event.results[0][0].transcript;
        // Find NiceGUI's input element and set its value
        const inputEl = document.querySelector('#voice-chat-input input, #voice-chat-input textarea');
        if (inputEl) {
            // Use NiceGUI's Quasar input — set native value and trigger input event
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(inputEl, transcript);
            inputEl.dispatchEvent(new Event('input', { bubbles: true }));
            // Brief delay then simulate Enter to submit
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
    };

    _voiceRecognition.onend = function() {
        _voiceIsListening = false;
        const btn = document.getElementById('mic-toggle-btn');
        if (btn) btn.classList.remove('mic-btn-recording');
        const status = document.getElementById('voice-status-label');
        if (status) { status.textContent = ''; status.style.display = 'none'; }
    };

    _voiceRecognition.start();
    return 'started';
}
</script>
""")


# ── Header (always visible) ──────────────────────────────────────
with ui.row().classes("app-header w-full items-center justify-between"):
    with ui.row().classes("items-center gap-3"):
        ui.html('<span class="mascot">🤖</span>')
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
        with ui.row().classes("w-full gap-4").style("min-height: 520px;"):

            # ── Chat column ───────────────────────────────────────
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

            # ── Code viewer column ────────────────────────────────
            with ui.column().classes("flex-1"):
                ui.html(
                    '<div class="section-title" style="color: var(--accent-purple);">'
                    '🧠 Robot\'s Brain</div>'
                )
                code_display = ui.html(
                    f'<pre class="code-viewer">{current_code}</pre>'
                )

                with ui.row().classes("gap-2 mt-2"):
                    ui.button(
                        "🚀 Go!", on_click=lambda: execute_code(),
                    ).classes("fun-btn fun-btn-primary").props("flat no-caps")
                    ui.button(
                        "🧹 Start Over", on_click=lambda: clear_code(),
                    ).classes("fun-btn fun-btn-ghost").props("flat no-caps")


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

                baud_select = ui.select(
                    options=[9600, 19200, 38400, 57600, 115200],
                    label="Speed",
                    value=115200,
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
                '🧠 AI Brain</div>'
            )
            with ui.column().classes("settings-card gap-4"):
                api_key_input = ui.input(
                    label="Secret AI Key",
                    placeholder="Paste your AI key here…",
                    password=True,
                    password_toggle_button=True,
                ).classes("nicegui-input w-full")

                ui.button(
                    "💾 Save Key",
                    on_click=lambda: save_api_key(),
                ).classes("fun-btn fun-btn-purple").props("flat no-caps").style("color: white !important;")

                gemini_status = ui.label(
                    "AI brain is sleeping (no key yet)"
                ).style("color: var(--text-medium); font-size: 0.9rem;")


# ── Status Bar ────────────────────────────────────────────────────
with ui.row().classes("status-bar w-full items-center justify-between"):
    ui.label("🤖 Miraloma Robotics v1.1").style("font-size: 0.85rem;")
    status_label = ui.label("✨ Ready to play!").style("font-size: 0.85rem; color: var(--primary); font-weight: 600;")


# ══════════════════════════════════════════════════════════════════
#  HANDLERS
# ══════════════════════════════════════════════════════════════════


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


def handle_emergency_stop() -> None:
    """Send emergency stop and update UI."""
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
    except Exception as e:
        serial_status.set_text(f"Oops! Something went wrong: {e}")
        ui.notify(f"❌ Couldn't connect: {e}", type="negative")


def handle_disconnect() -> None:
    """Disconnect from serial port."""
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

def save_api_key() -> None:
    """Save the Gemini API key."""
    key = api_key_input.value.strip()
    if not key:
        ui.notify("Type in your AI key first!", type="warning")
        return
    gemini.api_key = key
    gemini_status.set_text("✅ AI brain is awake!")
    ui.notify("🧠 AI brain activated!", type="positive")


async def send_chat_message() -> None:
    """Handle sending a chat message."""
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

    # Get AI response
    response = await gemini.send_message(text)

    # Assistant message
    with chat_container:
        ui.html(
            f'<div class="chat-msg chat-assistant">'
            f"{response}"
            f'<div class="chat-time">{now}</div></div>'
        )

    # Update code viewer if code was generated
    if gemini._on_code:
        # Check if code was generated by looking for keywords
        lower = text.lower()
        if any(kw in lower for kw in ("move", "drive", "scan", "forward", "back", "turn", "spin")):
            stub = gemini._generate_stub_code(text)
            current_code = stub
            code_display.set_content(
                f'<pre class="code-viewer">{_escape_html(stub)}</pre>'
            )

    status_label.set_text("✨ Ready to play!")


def execute_code() -> None:
    """Execute the current navigation script (stub — just notifies)."""
    if "No navigation script" in current_code:
        ui.notify("Tell the robot what to do first! 💬", type="warning")
        return
    ui.notify("🚀 Robot code will run soon! Coming in Phase 3", type="info")
    status_label.set_text("🚀 Running…")


def clear_code() -> None:
    """Clear the current navigation script."""
    global current_code
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
    host="0.0.0.0",
    port=8080,
    dark=False,
    reload=True,
)

