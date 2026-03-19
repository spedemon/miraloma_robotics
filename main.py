#!/usr/bin/env python3
"""
main.py — Robot Mind: Mission Control UI

NiceGUI application with 4 tabs:
  1. Workspace  — Chat + live code viewer + emergency stop
  2. Firmware   — Read-only STS code + copy button
  3. Protocol   — Auto-generated command reference table
  4. Settings   — Serial port, baud rate, API key
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path

from nicegui import ui, app

from robot_hal import RobotHAL
from gemini_client import GeminiClient

# ── Globals ───────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
robot = RobotHAL()
gemini = GeminiClient()

# Chat history: list of {"role": "user"|"assistant", "text": str, "time": str}
chat_history: list[dict] = []
# Currently displayed navigation code
current_code: str = "# No navigation script loaded yet."

# ── Default STS Firmware ─────────────────────────────────────────
DEFAULT_STS_CODE = r"""
// main.ts — Micro:bit V2 Peripheral Bridge
// Flash via MakeCode: https://makecode.microbit.org/

const WATCHDOG_TIMEOUT = 1000  // ms
let lastCommandTime = input.runningTime()

serial.redirect(SerialPin.USB_TX, SerialPin.USB_RX, BaudRate.BaudRate115200)

serial.onDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    let line = serial.readUntil(serial.delimiters(Delimiters.NewLine))
    lastCommandTime = input.runningTime()
    let parts = line.split(":")
    let cmd = parts[0]

    if (cmd === "M" && parts.length >= 5) {
        // Motor drive: M:L1:L2:R1:R2
        mecanumRobotV2.controlMotor(
            parseInt(parts[1]),
            parseInt(parts[2]),
            parseInt(parts[3]),
            parseInt(parts[4])
        )
    } else if (cmd === "S" && parts.length >= 2) {
        // Servo: S:ANGLE
        mecanumRobotV2.setServo(parseInt(parts[1]))
    } else if (cmd === "D") {
        // Distance query: D:?
        let dist = mecanumRobotV2.readDistance()
        serial.writeLine("" + dist)
    } else if (cmd === "I") {
        // IMU query: I:?
        let pitch = input.rotation(Rotation.Pitch)
        let roll  = input.rotation(Rotation.Roll)
        let head  = input.compassHeading()
        serial.writeLine("" + pitch + ":" + roll + ":" + head)
    } else if (cmd === "L" && parts.length >= 2) {
        // LED text: L:TEXT
        basic.showString(parts[1])
    } else if (cmd === "B" && parts.length >= 2) {
        // Buzzer: B:FREQ
        music.ringTone(parseInt(parts[1]))
        basic.pause(200)
        music.rest(1)
    }
})

// Safety watchdog
basic.forever(function () {
    if (input.runningTime() - lastCommandTime > WATCHDOG_TIMEOUT) {
        mecanumRobotV2.state()  // All-stop
    }
})
""".strip()


# ══════════════════════════════════════════════════════════════════
#  LOAD PROTOCOL MAP
# ══════════════════════════════════════════════════════════════════
def load_protocol_map() -> list[dict]:
    """Load command definitions from protocol_map.json."""
    path = BASE_DIR / "protocol_map.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        return data.get("commands", [])
    return []


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


def _build_protocol_table(commands: list[dict]) -> str:
    """Build an HTML table from the protocol map commands."""
    rows = ""
    for cmd in commands:
        params = ", ".join(
            f'{p["name"]}: {p["type"]}' for p in cmd.get("parameters", [])
        )
        rows += f"""
        <tr>
            <td><code>{_escape_html(cmd.get('id', ''))}</code></td>
            <td><code>{_escape_html(cmd.get('uart_command', ''))}</code></td>
            <td><code>{_escape_html(cmd.get('uart_example', ''))}</code></td>
            <td><code>{_escape_html(cmd.get('python_method', ''))}</code></td>
            <td>{_escape_html(cmd.get('description', ''))}</td>
            <td>{_escape_html(params) if params else '—'}</td>
        </tr>
        """
    return f"""
    <table class="protocol-table">
        <thead>
            <tr>
                <th>ID</th>
                <th>UART Command</th>
                <th>Example</th>
                <th>Python Method</th>
                <th>Description</th>
                <th>Parameters</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """


# ══════════════════════════════════════════════════════════════════
#  UI CONSTRUCTION
# ══════════════════════════════════════════════════════════════════

# Theme & custom CSS
ui.add_head_html("""
<style>
  :root {
    --accent: #00e5ff;
    --accent2: #7c4dff;
    --bg-dark: #0d1117;
    --bg-card: #161b22;
    --bg-input: #1c2333;
    --text-primary: #e6edf3;
    --text-muted: #8b949e;
    --danger: #ff4444;
  }
  body {
    background: var(--bg-dark) !important;
    color: var(--text-primary) !important;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
  }
  .q-tab-panel { background: var(--bg-dark) !important; }
  .q-tab--active { color: var(--accent) !important; }
  .q-tabs { background: var(--bg-card) !important; border-bottom: 1px solid #30363d; }
  .q-tab { color: var(--text-muted) !important; font-weight: 600; }

  /* Chat messages */
  .chat-msg {
    padding: 10px 14px;
    border-radius: 12px;
    margin: 4px 0;
    max-width: 85%;
    line-height: 1.5;
    font-size: 0.95rem;
  }
  .chat-user {
    background: linear-gradient(135deg, #7c4dff 0%, #448aff 100%);
    color: white;
    margin-left: auto;
    border-bottom-right-radius: 4px;
  }
  .chat-assistant {
    background: var(--bg-card);
    color: var(--text-primary);
    border: 1px solid #30363d;
    border-bottom-left-radius: 4px;
  }
  .chat-time {
    font-size: 0.7rem;
    color: var(--text-muted);
    margin-top: 2px;
  }

  /* Code viewer */
  .code-viewer {
    background: var(--bg-card) !important;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 16px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.85rem;
    white-space: pre-wrap;
    color: #79c0ff;
    overflow-y: auto;
    max-height: 320px;
  }

  /* Stop button */
  .stop-btn {
    background: linear-gradient(135deg, #ff4444, #cc0000) !important;
    color: white !important;
    font-weight: 800 !important;
    font-size: 1rem !important;
    border-radius: 12px !important;
    text-transform: uppercase;
    letter-spacing: 1px;
    box-shadow: 0 4px 20px rgba(255, 68, 68, 0.4);
    transition: all 0.2s ease;
  }
  .stop-btn:hover {
    box-shadow: 0 6px 28px rgba(255, 68, 68, 0.6);
    transform: translateY(-1px);
  }

  /* Settings card */
  .settings-card {
    background: var(--bg-card);
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 24px;
  }

  /* Protocol table */
  .protocol-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  .protocol-table th {
    background: var(--bg-card);
    color: var(--accent);
    padding: 12px 16px;
    text-align: left;
    border-bottom: 2px solid var(--accent);
    font-weight: 700;
  }
  .protocol-table td {
    padding: 10px 16px;
    border-bottom: 1px solid #21262d;
    color: var(--text-primary);
  }
  .protocol-table tr:hover td {
    background: rgba(0, 229, 255, 0.04);
  }
  .protocol-table code {
    background: var(--bg-input);
    color: #79c0ff;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
  }

  /* Connection badge */
  .conn-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
  }
  .conn-online {
    background: rgba(0, 229, 255, 0.15);
    color: var(--accent);
    border: 1px solid rgba(0, 229, 255, 0.3);
  }
  .conn-offline {
    background: rgba(255, 68, 68, 0.1);
    color: #ff6b6b;
    border: 1px solid rgba(255, 68, 68, 0.3);
  }

  /* Status bar */
  .status-bar {
    background: var(--bg-card);
    border-top: 1px solid #30363d;
    padding: 8px 20px;
    font-size: 0.8rem;
    color: var(--text-muted);
  }

  /* Header */
  .app-header {
    background: linear-gradient(90deg, var(--bg-card) 0%, #1a1f2e 100%);
    border-bottom: 1px solid #30363d;
    padding: 10px 24px;
  }
  .app-title {
    font-size: 1.3rem;
    font-weight: 800;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  /* Input styling */
  .nicegui-input .q-field__control {
    background: var(--bg-input) !important;
    border-radius: 8px !important;
  }
  .nicegui-input .q-field__native,
  .nicegui-input .q-field__label {
    color: var(--text-primary) !important;
  }
  .nicegui-select .q-field__control {
    background: var(--bg-input) !important;
    border-radius: 8px !important;
  }
</style>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
""")


# ── Header (always visible) ──────────────────────────────────────
with ui.row().classes("app-header w-full items-center justify-between"):
    with ui.row().classes("items-center gap-3"):
        ui.icon("smart_toy", size="28px").style("color: #00e5ff")
        ui.html('<span class="app-title">Miraloma Robotics</span>')
        ui.label("Mission Control").style("color: var(--text-muted); font-size: 0.85rem; margin-left: 4px;")

    with ui.row().classes("items-center gap-3"):
        connection_badge = ui.html(
            '<span class="conn-badge conn-offline">● Disconnected</span>'
        )
        stop_button = ui.button(
            "🛑 EMERGENCY STOP",
            on_click=lambda: handle_emergency_stop(),
        ).classes("stop-btn").props('flat no-caps')


# ── Tabs ──────────────────────────────────────────────────────────
with ui.tabs().classes("w-full") as tabs:
    tab_workspace = ui.tab("Workspace", icon="terminal")
    tab_firmware = ui.tab("Firmware (STS)", icon="memory")
    tab_protocol = ui.tab("Protocol Docs", icon="description")
    tab_settings = ui.tab("Settings", icon="settings")


with ui.tab_panels(tabs, value=tab_workspace).classes("w-full flex-grow"):

    # ══════════════════════════════════════════════════════════════
    #  TAB 1: WORKSPACE
    # ══════════════════════════════════════════════════════════════
    with ui.tab_panel(tab_workspace):
        with ui.row().classes("w-full gap-4").style("min-height: 520px;"):

            # ── Chat column ───────────────────────────────────────
            with ui.column().classes("flex-1"):
                ui.label("💬 Chat").style(
                    "font-weight: 700; font-size: 1rem; color: var(--accent); margin-bottom: 8px;"
                )
                chat_container = ui.column().classes(
                    "w-full flex-grow gap-1"
                ).style(
                    "overflow-y: auto; max-height: 400px; padding: 8px; "
                    "background: var(--bg-card); border-radius: 12px; border: 1px solid #30363d;"
                )

                # Welcome message
                with chat_container:
                    ui.html(
                        '<div class="chat-msg chat-assistant">'
                        "👋 <b>Welcome to Miraloma Robotics!</b><br>"
                        "Connect your robot in <b>Settings</b>, then tell me what to do.<br>"
                        '<span class="chat-time">System</span></div>'
                    )

                # Input row
                with ui.row().classes("w-full items-center gap-2 mt-2"):
                    chat_input = ui.input(
                        placeholder="Tell the robot what to do…"
                    ).classes("nicegui-input flex-grow").props(
                        'outlined dense'
                    ).on("keydown.enter", lambda: send_chat_message())

                    ui.button(
                        icon="send",
                        on_click=lambda: send_chat_message(),
                    ).props("flat round").style("color: var(--accent);")

            # ── Code viewer column ────────────────────────────────
            with ui.column().classes("flex-1"):
                ui.label("🧠 Live Navigation Script").style(
                    "font-weight: 700; font-size: 1rem; color: var(--accent2); margin-bottom: 8px;"
                )
                code_display = ui.html(
                    f'<pre class="code-viewer">{current_code}</pre>'
                )

                with ui.row().classes("gap-2 mt-2"):
                    ui.button(
                        "▶ Execute", on_click=lambda: execute_code(),
                    ).props("flat no-caps").style(
                        "background: rgba(0,229,255,0.1); color: var(--accent); font-weight: 600;"
                    )
                    ui.button(
                        "🗑 Clear", on_click=lambda: clear_code(),
                    ).props("flat no-caps").style(
                        "color: var(--text-muted);"
                    )


    # ══════════════════════════════════════════════════════════════
    #  TAB 2: FIRMWARE (STS)
    # ══════════════════════════════════════════════════════════════
    with ui.tab_panel(tab_firmware):
        with ui.column().classes("w-full gap-3"):
            ui.label("📟 Micro:bit Firmware (Static TypeScript)").style(
                "font-weight: 700; font-size: 1.1rem; color: var(--accent);"
            )
            ui.label(
                "Copy this code into MakeCode (makecode.microbit.org) and flash your Micro:bit V2."
            ).style("color: var(--text-muted); font-size: 0.9rem;")

            with ui.row().classes("gap-2"):
                ui.button(
                    "📋 Copy to Clipboard",
                    on_click=lambda: ui.run_javascript(
                        f"navigator.clipboard.writeText({json.dumps(DEFAULT_STS_CODE)})"
                        ".then(() => {{ }})"
                    ),
                ).props("flat no-caps").style(
                    "background: rgba(0,229,255,0.1); color: var(--accent); font-weight: 600;"
                )
                ui.button(
                    "🔗 Open MakeCode",
                    on_click=lambda: ui.run_javascript(
                        "window.open('https://makecode.microbit.org/', '_blank')"
                    ),
                ).props("flat no-caps").style(
                    "color: var(--accent2); font-weight: 600;"
                )

            ui.html(
                f'<pre class="code-viewer" style="max-height: 500px;">'
                f'{_escape_html(DEFAULT_STS_CODE)}</pre>'
            )


    # ══════════════════════════════════════════════════════════════
    #  TAB 3: PROTOCOL DOCS
    # ══════════════════════════════════════════════════════════════
    with ui.tab_panel(tab_protocol):
        ui.label("📖 UART Protocol Reference").style(
            "font-weight: 700; font-size: 1.1rem; color: var(--accent); margin-bottom: 12px;"
        )
        ui.label(
            f"Baud rate: 115200 · Format: CMD:VAL1:VAL2\\n"
        ).style("color: var(--text-muted); font-size: 0.9rem; margin-bottom: 16px;")

        commands = load_protocol_map()
        if commands:
            table_html = _build_protocol_table(commands)
            ui.html(table_html)
        else:
            ui.label("⚠ protocol_map.json not found.").style("color: var(--danger);")


    # ══════════════════════════════════════════════════════════════
    #  TAB 4: SETTINGS
    # ══════════════════════════════════════════════════════════════
    with ui.tab_panel(tab_settings):
        with ui.column().classes("w-full gap-6").style("max-width: 600px;"):

            # Serial section
            ui.label("🔌 Serial Connection").style(
                "font-weight: 700; font-size: 1.1rem; color: var(--accent);"
            )
            with ui.column().classes("settings-card gap-4"):
                ports = robot.list_ports()
                port_select = ui.select(
                    options=ports if ports else ["(no ports detected)"],
                    label="Serial Port",
                    value=ports[0] if ports else "(no ports detected)",
                ).classes("nicegui-select w-full")

                baud_select = ui.select(
                    options=[9600, 19200, 38400, 57600, 115200],
                    label="Baud Rate",
                    value=115200,
                ).classes("nicegui-select w-full")

                with ui.row().classes("gap-2"):
                    ui.button(
                        "🔗 Connect",
                        on_click=lambda: handle_connect(),
                    ).props("flat no-caps").style(
                        "background: rgba(0,229,255,0.1); color: var(--accent); font-weight: 600;"
                    )
                    ui.button(
                        "⛓️‍💥 Disconnect",
                        on_click=lambda: handle_disconnect(),
                    ).props("flat no-caps").style(
                        "color: var(--text-muted); font-weight: 600;"
                    )
                    ui.button(
                        "🔄 Refresh Ports",
                        on_click=lambda: refresh_ports(),
                    ).props("flat no-caps").style(
                        "color: var(--text-muted);"
                    )

                serial_status = ui.label("Status: Disconnected").style(
                    "color: var(--text-muted); font-size: 0.85rem;"
                )

            # Gemini section
            ui.label("🤖 Gemini AI").style(
                "font-weight: 700; font-size: 1.1rem; color: var(--accent2); margin-top: 8px;"
            )
            with ui.column().classes("settings-card gap-4"):
                api_key_input = ui.input(
                    label="Gemini API Key",
                    placeholder="Enter your Gemini API key…",
                    password=True,
                    password_toggle_button=True,
                ).classes("nicegui-input w-full")

                ui.button(
                    "💾 Save API Key",
                    on_click=lambda: save_api_key(),
                ).props("flat no-caps").style(
                    "background: rgba(124,77,255,0.1); color: var(--accent2); font-weight: 600;"
                )

                gemini_status = ui.label(
                    "Status: Stub mode (no API key)"
                ).style("color: var(--text-muted); font-size: 0.85rem;")


# ── Status Bar ────────────────────────────────────────────────────
with ui.row().classes("status-bar w-full items-center justify-between"):
    ui.label("Miraloma Robotics v1.0 — Phase 1 Foundation").style("font-size: 0.8rem;")
    status_label = ui.label("Ready").style("font-size: 0.8rem; color: var(--accent);")


# ══════════════════════════════════════════════════════════════════
#  HANDLERS
# ══════════════════════════════════════════════════════════════════


def handle_emergency_stop() -> None:
    """Send emergency stop and update UI."""
    try:
        robot.stop()
        ui.notify("🛑 EMERGENCY STOP sent!", type="negative", position="top")
    except ConnectionError:
        ui.notify("⚠ Robot not connected — stop command not sent", type="warning", position="top")
    status_label.set_text("⚠ EMERGENCY STOP")


def handle_connect() -> None:
    """Connect to the selected serial port."""
    port = port_select.value
    baud = baud_select.value
    if not port or port == "(no ports detected)":
        ui.notify("No serial port selected", type="warning")
        return
    try:
        robot.connect(port, baud)
        serial_status.set_text(f"Status: Connected to {port} @ {baud}")
        connection_badge.set_content(
            '<span class="conn-badge conn-online">● Connected</span>'
        )
        status_label.set_text(f"Connected to {port}")
        ui.notify(f"✅ Connected to {port}", type="positive")
    except Exception as e:
        serial_status.set_text(f"Status: Error — {e}")
        ui.notify(f"❌ Connection failed: {e}", type="negative")


def handle_disconnect() -> None:
    """Disconnect from serial port."""
    robot.disconnect()
    serial_status.set_text("Status: Disconnected")
    connection_badge.set_content(
        '<span class="conn-badge conn-offline">● Disconnected</span>'
    )
    status_label.set_text("Disconnected")
    ui.notify("Disconnected", type="info")


def refresh_ports() -> None:
    """Refresh the list of available serial ports."""
    ports = robot.list_ports()
    port_select.options = ports if ports else ["(no ports detected)"]
    port_select.value = ports[0] if ports else "(no ports detected)"
    port_select.update()
    ui.notify(f"Found {len(ports)} port(s)", type="info")


def save_api_key() -> None:
    """Save the Gemini API key."""
    key = api_key_input.value.strip()
    if not key:
        ui.notify("Please enter an API key", type="warning")
        return
    gemini.api_key = key
    gemini_status.set_text("Status: API key saved (real AI coming in Phase 3)")
    ui.notify("🔑 API key saved", type="positive")


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

    status_label.set_text("🤖 Thinking…")

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

    status_label.set_text("Ready")


def execute_code() -> None:
    """Execute the current navigation script (stub — just notifies)."""
    if "No navigation script" in current_code:
        ui.notify("No script to execute. Send a movement command first.", type="warning")
        return
    ui.notify("▶ Code execution coming in Phase 3!", type="info")
    status_label.set_text("▶ Executing…")


def clear_code() -> None:
    """Clear the current navigation script."""
    global current_code
    current_code = "# No navigation script loaded yet."
    code_display.set_content(
        f'<pre class="code-viewer">{current_code}</pre>'
    )
    status_label.set_text("Ready")


# ══════════════════════════════════════════════════════════════════
#  LAUNCH
# ══════════════════════════════════════════════════════════════════
ui.run(
    title="Miraloma Robotics — Mission Control",
    host="0.0.0.0",
    port=8080,
    dark=True,
    reload=True,
)
