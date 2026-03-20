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
import uuid
import wave
import yaml
import threading
from datetime import datetime
from pathlib import Path
import argparse

from nicegui import ui, app

# BASE_DIR must be defined before mounting static files
_BASE_DIR_EARLY = Path(__file__).parent

# Serve static assets (logo, etc.)
app.add_static_files('/static', str(_BASE_DIR_EARLY / 'static'))

# ── TTS Audio ─────────────────────────────────────────────────────
# WAV clips are written to static/tts/ and served as regular static files.
_TTS_DIR = _BASE_DIR_EARLY / 'static' / 'tts'
_TTS_DIR.mkdir(parents=True, exist_ok=True)

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
# Track whether the current chat was initiated by voice
_voice_initiated: bool = False
# Flag to prevent double-processing of voice results
_processing_voice: bool = False
# Track whether the last auto-launched action completed (for "Go Again!" UX)
_auto_action_done: bool = False

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
<link rel="stylesheet" href="/static/style.css">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
""")


# ── Voice input JavaScript (Web Speech API) ──────────────────────
ui.add_head_html("""
<script>
let _voiceRecognition = null;
let _voiceIsListening = false;
let _voiceGotResult = false;

function setRobotFaceState(state) {
    const container = document.getElementById('robot-face-outer');
    if (!container) return;
    container.classList.remove('robot-face-idle', 'robot-face-listening', 'robot-face-thinking', 'robot-face-talking');
    container.classList.add('robot-face-' + state);
    const label = document.getElementById('face-state-text');
    if (label) {
        if (state === 'listening') label.textContent = '🎙️ Listening…';
        else if (state === 'thinking') label.textContent = '🧠 Thinking…';
        else if (state === 'talking') label.textContent = '🔊 Speaking…';
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
    _voiceGotResult = false;

    _voiceRecognition.onstart = function() {
        _voiceIsListening = true;
        _voiceGotResult = false;
        const btn = document.getElementById('mic-toggle-btn');
        if (btn) btn.classList.add('mic-btn-recording');
        const status = document.getElementById('voice-status-label');
        if (status) { status.textContent = '🎙️ Listening…'; status.style.display = 'block'; }
        setRobotFaceState('listening');
    };

    _voiceRecognition.onresult = function(event) {
        if (_voiceGotResult) return;
        const transcript = event.results[0][0].transcript;
        if (!transcript) return;
        _voiceGotResult = true;
        
        // Store transcript and click hidden button to notify Python
        window._voiceTranscript = transcript;
        const btn = document.getElementById('voice-hidden-submit');
        if (btn) btn.click();
        
        // Stop recognition immediately to prevent further results
        _voiceRecognition.stop();
    };

    _voiceRecognition.onerror = function(event) {
        console.warn('Speech recognition error:', event.error);
        _voiceIsListening = false;
        _voiceGotResult = false;
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
        // If we got a result, transition to thinking (send_chat_message handles idle).
        // Otherwise (manual cancel / no speech detected), go back to idle.
        if (_voiceGotResult) {
            setRobotFaceState('thinking');
        } else {
            setRobotFaceState('idle');
        }
    };

    _voiceRecognition.start();
    return 'started';
}

// ── Text-to-Speech (Gemini TTS via server audio) ──────────────
let _ttsAudio = null;

function playGeminiAudio(url) {
    stopSpeaking();
    _ttsAudio = new Audio(url);
    _ttsAudio.onplay = function() {
        setRobotFaceState('talking');
    };
    _ttsAudio.onended = function() {
        setRobotFaceState('idle');
        _ttsAudio = null;
    };
    _ttsAudio.onerror = function() {
        setRobotFaceState('idle');
        _ttsAudio = null;
    };
    _ttsAudio.play().catch(function(e) {
        console.warn('Audio play failed:', e);
        setRobotFaceState('idle');
    });
}

function stopSpeaking() {
    if (_ttsAudio) {
        _ttsAudio.pause();
        _ttsAudio.currentTime = 0;
        _ttsAudio = null;
    }
}

// ── Progress Bar Control (horizontal bar under robot face) ─────
let _progressTimer = null;
let _progressStart = 0;
let _progressDuration = 0;

function startDeterminateProgress(durationSec) {
    stopProgressAnimation();
    _progressDuration = durationSec * 1000;
    _progressStart = performance.now();
    const area = document.getElementById('progress-bar-area');
    const fill = document.getElementById('progress-bar-fill');
    const label = document.getElementById('progress-bar-label');
    const stateText = document.getElementById('face-state-text');
    if (!area || !fill) return;
    fill.classList.remove('indeterminate');
    fill.style.width = '0%';
    area.classList.add('progress-active');
    if (stateText) stateText.textContent = '🚀 Moving — Ready to Chat!';
    _progressTimer = setInterval(() => {
        const elapsed = performance.now() - _progressStart;
        const ratio = Math.min(elapsed / _progressDuration, 1);
        fill.style.width = Math.round(ratio * 100) + '%';
        if (label) label.textContent = Math.round(ratio * 100) + '%';
        if (ratio >= 1) clearInterval(_progressTimer);
    }, 50);
}

function startIndeterminateProgress() {
    stopProgressAnimation();
    const area = document.getElementById('progress-bar-area');
    const fill = document.getElementById('progress-bar-fill');
    const label = document.getElementById('progress-bar-label');
    const stateText = document.getElementById('face-state-text');
    if (!area || !fill) return;
    fill.style.width = '';
    fill.classList.add('indeterminate');
    area.classList.add('progress-active');
    if (label) label.textContent = '';
    if (stateText) stateText.textContent = '🧭 Navigating — Ready to Chat!';
}

function stopProgressAnimation() {
    if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null; }
    const area = document.getElementById('progress-bar-area');
    const fill = document.getElementById('progress-bar-fill');
    const label = document.getElementById('progress-bar-label');
    const stateText = document.getElementById('face-state-text');
    if (area) area.classList.remove('progress-active');
    if (fill) { fill.classList.remove('indeterminate'); fill.style.width = '0%'; }
    if (label) label.textContent = '';
    if (stateText) stateText.textContent = '😊 Ready to chat!';
}
</script>
""")


# ── Header (always visible) ──────────────────────────────────────
with ui.row().classes("app-header w-full items-center justify-between"):
    with ui.row().classes("items-center gap-3"):
        ui.html(f'<img src="{LOGO_URL}" class="mascot-img" alt="Robot Logo">')
        with ui.column().classes("gap-0"):
            ui.html('<span class="app-title">Miraloma Robots</span>')
            ui.html('<span class="app-subtitle">Robot Brain Designer</span>')

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
                    ).props('id=chat-scroll-container')

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

                    # Hidden button for JS→Python voice transcript delivery
                    voice_hidden_btn = ui.button(
                        '', on_click=lambda: _on_voice_hidden_click(),
                    ).props('id=voice-hidden-submit').style(
                        'position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden;'
                    )

                # ── Robot Face column ─────────────────────────────
                with ui.column().classes("flex-1 items-center justify-center"):
                    robot_face_html = ui.html('''
                    <div id="robot-face-outer" class="robot-face-idle">
                      <div class="robot-face-container">
                        <div class="face-glow"></div>
                        <div class="robot-face-wrapper">
                          <svg viewBox="-50 -50 360 380" width="280" height="300" xmlns="http://www.w3.org/2000/svg">
                            <!-- Sound waves (visible when listening) -->
                            <circle class="sound-wave" cx="130" cy="120" r="100" fill="none" stroke="#FF6B35" stroke-width="2"/>
                            <circle class="sound-wave" cx="130" cy="120" r="100" fill="none" stroke="#FF6B35" stroke-width="2"/>
                            <circle class="sound-wave" cx="130" cy="120" r="100" fill="none" stroke="#FF6B35" stroke-width="2"/>

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
                      <div id="progress-bar-area" class="progress-bar-area">
                        <div class="progress-bar-track">
                          <div id="progress-bar-fill" class="progress-bar-fill"></div>
                        </div>
                        <div id="progress-bar-label" class="progress-bar-label"></div>
                      </div>
                    </div>
                    ''')

            # ── Action buttons (always visible) ─────────────────────
            with ui.row().classes("gap-2 w-full items-center"):
                go_stop_button = ui.button(
                    "🚀 Go!", on_click=lambda: toggle_go_stop(),
                ).classes("fun-btn fun-btn-primary").props("flat no-caps").style("min-width: 130px;")
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
    _reset_play_ui()
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


async def _on_voice_hidden_click() -> None:
    """Hidden button click handler — retrieves transcript from JS global."""
    transcript = await ui.run_javascript(
        "(() => { const t = window._voiceTranscript || ''; window._voiceTranscript = ''; return t; })()"
    )
    if transcript:
        await handle_voice_result(transcript)


async def handle_voice_result(text: str) -> None:
    """Handle a voice transcript received from the browser."""
    global _voice_initiated, _processing_voice
    if not text or _processing_voice:
        return
        
    try:
        _processing_voice = True
        # Mark this interaction as voice-initiated (for TTS response)
        _voice_initiated = True
        # Set the chat input so send_chat_message can read it
        chat_input.value = text
        await send_chat_message()
    finally:
        _processing_voice = False

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
    global current_code, _voice_initiated
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
    # Auto-scroll chat to bottom
    await ui.run_javascript(
        "document.getElementById('chat-scroll-container').scrollTop = "
        "document.getElementById('chat-scroll-container').scrollHeight"
    )

    status_label.set_text("🤖 Robot is thinking…")
    await ui.run_javascript("setRobotFaceState('thinking')")

    try:
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
        # Auto-scroll chat to bottom
        await ui.run_javascript(
            "document.getElementById('chat-scroll-container').scrollTop = "
            "document.getElementById('chat-scroll-container').scrollHeight"
        )

        # Speak the response aloud if this was a voice-initiated interaction
        if _voice_initiated and display_text.strip():
            _voice_initiated = False
            # Use Gemini TTS to synthesize and play the response
            try:
                pcm_data = await gemini.synthesize_speech(display_text)
                if pcm_data:
                    # Wrap PCM in WAV and write to static/tts/ for HTTP serving
                    audio_id = uuid.uuid4().hex
                    wav_path = _TTS_DIR / f'{audio_id}.wav'
                    with wave.open(str(wav_path), 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(24000)
                        wf.writeframes(pcm_data)
                    audio_url = f'/static/tts/{audio_id}.wav'
                    await ui.run_javascript(f"playGeminiAudio('{audio_url}')")
                    # Clean up file after a delay (let browser finish fetching)
                    async def _cleanup():
                        await asyncio.sleep(30)
                        wav_path.unlink(missing_ok=True)
                    asyncio.create_task(_cleanup())
                else:
                    print("[TTS] WARNING: synthesize_speech returned None/empty")
            except Exception as tts_exc:
                print(f"[TTS] ERROR in TTS flow: {tts_exc}")

        # Handle code if present
        if parsed.has_code:
            _auto_action_done = False
            current_code = parsed.code
            code_display.set_content(
                f'<pre class="code-viewer" style="margin: 0; border: none; '
                f'border-radius: 0 0 var(--radius-md) var(--radius-md);">'
                f'{_escape_html(parsed.code)}</pre>'
            )
            # Auto-expand the code panel
            code_expansion.open()

            if parsed.response_type == ResponseType.ACTION:
                # Return face to idle after AI processing, before action
                await ui.run_javascript("setRobotFaceState('idle')")
                # Auto-execute action commands immediately
                status_label.set_text("🚀 Running action…")
                await _execute_code_async(parsed.code, mode="action", auto_launched=True)
            elif parsed.response_type == ResponseType.NAVIGATION:
                # Return face to idle after AI processing
                await ui.run_javascript("setRobotFaceState('idle')")
                # Wait for Go! button
                status_label.set_text("📋 Navigation ready — press Go! to start")
                ui.notify(
                    "🧭 Navigation script ready! Press 🚀 Go! to start.",
                    type="info",
                )
        else:
            if not _voice_initiated:
                await ui.run_javascript("setRobotFaceState('idle')")
            status_label.set_text("✨ Ready to play!")
    except Exception as exc:
        # Ensure we always recover from the thinking state
        await ui.run_javascript("setRobotFaceState('idle')")
        status_label.set_text("✨ Ready to play!")
        raise


def _estimate_duration(code: str) -> float | None:
    """Estimate total duration of an ACTION script by summing wait() calls.

    Returns None for NAVIGATION scripts (contain while is_running()).
    """
    import re
    if "while" in code and "is_running()" in code:
        return None
    total = 0.0
    for m in re.finditer(r'wait\s*\(\s*([\d.]+)\s*\)', code):
        total += float(m.group(1))
    return total if total > 0 else None


def _set_go_stop_button(running: bool, replay: bool = False) -> None:
    """Toggle Go!/Stop/Go Again! button appearance."""
    if running:
        go_stop_button.set_text("🛑 Stop")
        go_stop_button._classes = [c for c in go_stop_button._classes if c != 'fun-btn-primary']
        go_stop_button._classes.append('stop-btn')
        go_stop_button.update()
    else:
        go_stop_button.set_text("🔄 Go Again!" if replay else "🚀 Go!")
        go_stop_button._classes = [c for c in go_stop_button._classes if c != 'stop-btn']
        if 'fun-btn-primary' not in go_stop_button._classes:
            go_stop_button._classes.append('fun-btn-primary')
        go_stop_button.update()


def _reset_play_ui() -> None:
    """Reset progress animation and Go/Stop button."""
    _set_go_stop_button(False)
    ui.run_javascript("stopProgressAnimation()")


async def _execute_code_async(code: str, mode: str = "action", auto_launched: bool = False) -> None:
    """Execute generated Python code in a background task."""
    global _running_task, _auto_action_done

    # Stop any currently running code
    stop_execution()

    # Set up the runtime
    nav_runtime.running = True
    _auto_action_done = False
    _set_go_stop_button(True)

    # Start the appropriate animation
    if mode == "navigation":
        await ui.run_javascript("startIndeterminateProgress()")
    else:
        duration = _estimate_duration(code)
        if duration and duration > 0:
            await ui.run_javascript(f"startDeterminateProgress({duration})")
        else:
            # Fallback: treat unknown duration as indeterminate
            await ui.run_javascript("startIndeterminateProgress()")

    _was_cancelled = False

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

    _running_task = asyncio.create_task(_run())

    # Wait for task to finish, then clean up in the NiceGUI client context
    try:
        await _running_task
    except asyncio.CancelledError:
        _was_cancelled = True
    finally:
        nav_runtime.running = False
        ui.run_javascript("stopProgressAnimation()")
        ui.run_javascript("setRobotFaceState('idle')")
        # Show "Go Again!" if this was an auto-launched action that completed normally
        if auto_launched and mode == "action" and not _was_cancelled:
            _auto_action_done = True
            _set_go_stop_button(False, replay=True)
            status_label.set_text("✅ Done! Press Go! to repeat")
        else:
            _set_go_stop_button(False)
            status_label.set_text("✨ Ready to play!")


def stop_execution() -> None:
    """Stop any running navigation code and speech."""
    global _running_task
    nav_runtime.running = False
    if _running_task and not _running_task.done():
        _running_task.cancel()
    _running_task = None
    # Stop any text-to-speech in progress
    ui.run_javascript("stopSpeaking()")


async def toggle_go_stop() -> None:
    """Toggle between Go! and Stop based on execution state."""
    if nav_runtime.running:
        # Currently running → stop
        stop_execution()
        _reset_play_ui()
        try:
            robot.stop()
        except ConnectionError:
            pass
        status_label.set_text("🛑 Stopped!")
        ui.notify("🛑 Script stopped!", type="negative")
    else:
        # Not running → execute
        await execute_code()


async def execute_code() -> None:
    """Execute the current navigation script (triggered by Go! button)."""
    global _auto_action_done
    if "No navigation script" in current_code:
        ui.notify("Tell the robot what to do first! 💬", type="warning")
        return
    # Determine mode from the code content
    mode = "navigation" if ("while" in current_code and "is_running()" in current_code) else "action"
    # Keep auto_launched=True for replays so "Go Again!" persists after each run
    is_replay = _auto_action_done
    _auto_action_done = False
    status_label.set_text("🚀 Running…")
    await _execute_code_async(current_code, mode=mode, auto_launched=is_replay)


def clear_code() -> None:
    """Clear the current navigation script, stop execution, and stop speech."""
    global current_code, _auto_action_done
    stop_execution()
    _auto_action_done = False
    _reset_play_ui()
    try:
        robot.stop()
    except ConnectionError:
        pass
    current_code = "# No navigation script loaded yet."
    code_display.set_content(
        f'<pre class="code-viewer">{current_code}</pre>'
    )
    status_label.set_text("✨ Ready to play!")
    ui.run_javascript("stopSpeaking()")


# ══════════════════════════════════════════════════════════════════
#  LAUNCH
# ══════════════════════════════════════════════════════════════════
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
        reload=not args.native,  # reload is usually incompatible with native=True in some environments
    )

