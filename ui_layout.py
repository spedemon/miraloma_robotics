"""
ui_layout.py — NiceGUI UI Construction

Builds the full UI layout (header, tabs, workspace, firmware,
protocol, settings panels) and returns a SimpleNamespace of widget
references so handlers.py can update them.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from nicegui import ui

from gemini_client import AVAILABLE_MODELS, DEFAULT_MODEL_LABEL
import handlers

# Read the robot face SVG once at import time so it can be inlined.
# It must be inline (not <object>) for CSS animations to work.
_ROBOT_FACE_SVG = (Path(__file__).parent / 'static' / 'robot_face.svg').read_text()


# ── Exported builder ─────────────────────────────────────────────

def build_ui(
    *,
    logo_url: str,
    selected_robot: str,
    available_robots: list[str],
    initial_config: dict,
    initial_firmware: str,
    initial_filename: str,
    initial_platform: dict,
    robot_hal,
    gemini_client,
    calibration: dict,
    saved: dict,
    current_code: str,
) -> SimpleNamespace:
    """Build the full NiceGUI interface and return widget references."""

    refs = SimpleNamespace()

    # Mutable state dict so button lambdas always read current values
    refs.firmware_state = {
        "source": initial_firmware,
        "open_url": initial_platform["open_url"] if initial_platform else "",
    }

    # ── Head: CSS + JS ────────────────────────────────────────────
    ui.add_head_html("""
    <link rel="stylesheet" href="/static/style.css">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="/static/app.js"></script>
    """)

    # ── Header ────────────────────────────────────────────────────
    with ui.row().classes("app-header w-full items-center justify-between"):
        with ui.row().classes("items-center gap-3"):
            ui.html(f'<img src="{logo_url}" class="mascot-img" alt="Robot Logo">')
            with ui.column().classes("gap-0"):
                ui.html('<span class="app-title">Miraloma Robots</span>')
                ui.html('<span class="app-subtitle">Robot Brain Designer</span>')

        with ui.row().classes("items-center gap-3"):
            refs.robot_badge = ui.html(
                f'<span class="robot-badge">🤖 {selected_robot.capitalize() if selected_robot else "No Robot"}</span>'
            )
            refs.connection_badge = ui.html(
                '<span class="conn-badge conn-offline">😴 Robot is sleeping</span>'
            )
            ui.button(
                "🛑 STOP",
                on_click=lambda: handlers.handle_emergency_stop(),
            ).classes("stop-btn").props('flat no-caps')

    # ── Tabs ──────────────────────────────────────────────────────
    with ui.tabs().classes("w-full") as tabs:
        tab_workspace = ui.tab("Play", icon="sports_esports")
        tab_firmware = ui.tab("Robot Code", icon="code")
        tab_protocol = ui.tab("Command Book", icon="auto_stories")
        tab_settings = ui.tab("Setup", icon="tune")

    with ui.tab_panels(tabs, value=tab_workspace).classes("w-full flex-grow"):

        # ══════════════════════════════════════════════════════════
        #  TAB 1: WORKSPACE
        # ══════════════════════════════════════════════════════════
        with ui.tab_panel(tab_workspace):
            _build_workspace_tab(refs, current_code)

        # ══════════════════════════════════════════════════════════
        #  TAB 2: FIRMWARE
        # ══════════════════════════════════════════════════════════
        with ui.tab_panel(tab_firmware):
            _build_firmware_tab(refs, initial_platform, initial_firmware, initial_filename)

        # ══════════════════════════════════════════════════════════
        #  TAB 3: PROTOCOL DOCS
        # ══════════════════════════════════════════════════════════
        with ui.tab_panel(tab_protocol):
            _build_protocol_tab(refs, selected_robot, initial_config)

        # ══════════════════════════════════════════════════════════
        #  TAB 4: SETTINGS
        # ══════════════════════════════════════════════════════════
        with ui.tab_panel(tab_settings):
            _build_settings_tab(
                refs,
                available_robots=available_robots,
                selected_robot=selected_robot,
                initial_config=initial_config,
                robot_hal=robot_hal,
                gemini_client=gemini_client,
                calibration=calibration,
                saved=saved,
            )

    # ── Status Bar ────────────────────────────────────────────────
    with ui.row().classes("status-bar w-full items-center justify-between"):
        ui.label("🤖 Miraloma Robotics v1.1").style("font-size: 0.85rem;")
        refs.status_label = ui.label("✨ Ready to play!").style(
            "font-size: 0.85rem; color: var(--primary); font-weight: 600;"
        )

    return refs


# ── Tab builders (private) ────────────────────────────────────────

def _build_workspace_tab(refs, current_code: str):
    """Build the Workspace tab: chat + robot face + code viewer."""
    with ui.column().classes("w-full gap-3"):
        with ui.row().classes("w-full gap-4").style("min-height: 460px;"):

            # ── Chat column ───────────────────────────────────
            with ui.column().classes("flex-1"):
                ui.html(
                    '<div class="section-title" style="color: var(--primary);">'
                    '💬 Talk to Your Robot!</div>'
                )
                refs.chat_container = ui.column().classes(
                    "w-full flex-grow gap-1"
                ).style(
                    "overflow-y: auto; max-height: 400px; padding: 12px; "
                    "background: var(--bg-card); border-radius: var(--radius-lg); "
                    "border: 2px solid #F0E6D8; box-shadow: var(--shadow-card);"
                ).props('id=chat-scroll-container')

                with refs.chat_container:
                    ui.html(
                        '<div class="chat-msg chat-assistant">'
                        "👋 <b>Hey there, Robot Commander!</b><br>"
                        "Pick your robot in <b>⚙️ Setup</b>, plug it in, then tell me what cool things to do!<br>"
                        '<span class="chat-time">Robot Brain</span></div>'
                    )

                with ui.row().classes("w-full items-center gap-2 mt-2"):
                    refs.chat_input = ui.input(
                        placeholder="What should the robot do? 🤔"
                    ).classes("nicegui-input flex-grow").props(
                        'outlined dense id=voice-chat-input'
                    ).on("keydown.enter", lambda: handlers.send_chat_message())

                    ui.button(
                        icon="mic",
                        on_click=lambda: handlers.handle_voice_toggle(),
                    ).props("flat round").classes("mic-btn").props(
                        'id=mic-toggle-btn'
                    )

                    ui.button(
                        icon="send",
                        on_click=lambda: handlers.send_chat_message(),
                    ).props("flat round").style("color: var(--primary); font-size: 1.2rem;")

                ui.html(
                    '<span id="voice-status-label" class="voice-status" style="display: none;"></span>'
                )

                ui.button(
                    '', on_click=lambda: handlers._on_voice_hidden_click(),
                ).props('id=voice-hidden-submit').style(
                    'position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden;'
                )

            # ── Robot Face column ─────────────────────────────
            with ui.column().classes("flex-1 items-center justify-center"):
                ui.html(f'''
                <div id="robot-face-outer" class="robot-face-idle">
                  <div class="robot-face-container">
                    <div class="face-glow"></div>
                    <div class="robot-face-wrapper">
                      {_ROBOT_FACE_SVG}
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

        # ── Action buttons ─────────────────────────────────────
        with ui.row().classes("gap-2 w-full items-center"):
            refs.go_stop_button = ui.button(
                "🚀 Go!", on_click=lambda: handlers.toggle_go_stop(),
            ).classes("fun-btn fun-btn-primary").props("flat no-caps").style("min-width: 130px;")
            ui.button(
                "🧹 Start Over", on_click=lambda: handlers.clear_code(),
            ).classes("fun-btn fun-btn-ghost").props("flat no-caps")

        # ── Collapsible code viewer ───────────────────────────
        with ui.expansion(
            "🧠 Navigation Script", icon="code",
        ).classes("w-full code-expansion").props("dense") as code_expansion:
            refs.code_expansion = code_expansion
            refs.code_display = ui.codemirror(
                value=current_code,
                language="python",
                theme="dracula"
            ).classes("w-full h-80 q-mt-md code-viewer-edit")


def _escape_html(text: str) -> str:
    """Escape HTML special characters for safe display."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_firmware_tab(refs, initial_platform, initial_firmware, initial_filename):
    """Build the Firmware tab."""
    firmware_container = ui.column().classes("w-full gap-3")
    with firmware_container:
        refs.firmware_title = ui.html(
            f'<div class="section-title" style="color: var(--primary);">'
            f'{initial_platform["icon"]} {initial_platform["label"]} Code</div>'
        )
        refs.firmware_instructions = ui.label(
            initial_platform["copy_instructions"]
        ).style("color: var(--text-medium); font-size: 0.95rem;")

        with ui.row().classes("gap-2"):
            ui.button(
                "📋 Copy Code",
                on_click=lambda: ui.run_javascript(
                    f"navigator.clipboard.writeText({json.dumps(refs.firmware_state['source'])})"
                    ".then(() => { })"
                ),
            ).classes("fun-btn fun-btn-secondary").props("flat no-caps")
            refs.firmware_open_btn = ui.button(
                initial_platform["open_label"],
                on_click=lambda: ui.run_javascript(
                    f"window.open('{refs.firmware_state['open_url']}', '_blank')"
                ),
            ).classes("fun-btn fun-btn-purple").props("flat no-caps").style("color: white !important;")

        refs.firmware_code_display = ui.html(
            f'<pre class="code-viewer" style="max-height: 500px;">'
            f'{_escape_html(initial_firmware)}</pre>'
        )
        refs.firmware_filename_label = ui.label(
            f"📄 {initial_filename}"
        ).style("color: var(--text-medium); font-size: 0.85rem; margin-top: 4px;")


def _build_protocol_tab(refs, selected_robot, initial_config):
    """Build the Protocol Docs tab."""
    protocol_container = ui.column().classes("w-full gap-3")
    with protocol_container:
        ui.html(
            '<div class="section-title" style="color: var(--primary);">'
            '📖 Robot Command Book</div>'
        )
        refs.protocol_meta = ui.label(
            f"Robot: {selected_robot.capitalize()} · "
            f"Platform: {initial_config.get('firmware_platform', '?')} · "
            f"Speed: {initial_config.get('baud_rate', '?')}"
        ).style("color: var(--text-medium); font-size: 0.95rem; margin-bottom: 12px;")

        if initial_config:
            refs.protocol_table_html = ui.html(
                handlers._build_protocol_table(initial_config)
            )
        else:
            refs.protocol_table_html = ui.html(
                '<span style="color: var(--danger); font-size: 1.1rem;">⚠️ No commands found for this robot.</span>'
            )


def _build_settings_tab(refs, *, available_robots, selected_robot, initial_config,
                        robot_hal, gemini_client, calibration, saved):
    """Build the Settings tab."""
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
            ui.select(
                options=robot_options,
                label="Which robot?",
                value=selected_robot,
                on_change=lambda e: handlers.handle_robot_change(e.value),
            ).classes("nicegui-select w-full")

            refs.robot_platform_label = ui.label(
                f"Type: {initial_config.get('firmware_platform', '').upper()}"
            ).style("color: var(--text-medium); font-size: 0.9rem;")

        # Serial section
        ui.html(
            '<div class="section-title" style="color: var(--secondary);">'
            '🔌 Connect Your Robot!</div>'
        )
        with ui.column().classes("settings-card gap-4"):
            ports = robot_hal.list_ports()
            refs.port_select = ui.select(
                options=ports if ports else ["(no robot found)"],
                label="USB Port",
                value=ports[0] if ports else "(no robot found)",
            ).classes("nicegui-select w-full")

            _saved_baud = saved["uart_baud"] if saved["uart_baud"] in [9600, 19200, 38400, 57600, 115200] else 115200
            refs.baud_select = ui.select(
                options=[9600, 19200, 38400, 57600, 115200],
                label="Speed",
                value=_saved_baud,
            ).classes("nicegui-select w-full")

            with ui.row().classes("gap-2"):
                ui.button(
                    "🔌 Plug In!",
                    on_click=lambda: handlers.handle_connect(),
                ).classes("fun-btn fun-btn-secondary").props("flat no-caps")
                ui.button(
                    "🚫 Unplug",
                    on_click=lambda: handlers.handle_disconnect(),
                ).classes("fun-btn fun-btn-ghost").props("flat no-caps")
                ui.button(
                    "🔄 Look Again",
                    on_click=lambda: handlers.refresh_ports(),
                ).classes("fun-btn fun-btn-ghost").props("flat no-caps")

            refs.serial_status = ui.label("Not connected yet").style(
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

            refs.api_key_input = ui.input(
                label="Gemini API Key",
                placeholder="Paste your API key here (starts with AIza…)",
                value=saved["api_key"],
                password=True,
                password_toggle_button=True,
            ).classes("nicegui-input w-full")

            model_options = {label: label for label in gemini_client.available_model_labels()}
            _saved_model = saved["model"] if saved["model"] in model_options else DEFAULT_MODEL_LABEL
            refs.model_select = ui.select(
                options=model_options,
                label="AI Model",
                value=_saved_model,
                on_change=lambda e: handlers.handle_model_change(e.value),
            ).classes("nicegui-select w-full")

            with ui.row().classes("gap-2"):
                ui.button(
                    "🚀 Save & Test",
                    on_click=lambda: handlers.save_api_key(),
                ).classes("fun-btn fun-btn-purple").props("flat no-caps").style("color: white !important;")

                ui.button(
                    "🔗 Get API Key",
                    on_click=lambda: ui.run_javascript(
                        "window.open('https://aistudio.google.com/apikey', '_blank')"
                    ),
                ).classes("fun-btn fun-btn-ghost").props("flat no-caps")

            refs.gemini_status = ui.label(
                f"✅ AI brain is awake — using {gemini_client.model_label}" if gemini_client.is_connected
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

            ui.number(
                label="Speed (seconds per foot)",
                value=calibration["speed_seconds_per_foot"],
                min=0.5, max=30.0, step=0.5,
                on_change=lambda e: handlers.handle_calibration_change("speed_seconds_per_foot", e.value),
            ).classes("nicegui-input w-full")

            ui.number(
                label="Default Motor Speed (0–255)",
                value=calibration["default_motor_speed"],
                min=0, max=255, step=10,
                on_change=lambda e: handlers.handle_calibration_change("default_motor_speed", int(e.value)),
            ).classes("nicegui-input w-full")

            refs.cal_status = ui.label(
                f"📏 {calibration['speed_seconds_per_foot']} sec/foot · "
                f"🏎️ Motor speed: {calibration['default_motor_speed']}"
            ).style("color: var(--text-medium); font-size: 0.9rem;")
