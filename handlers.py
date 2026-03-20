"""
handlers.py — Event Handlers & Execution Logic

All user-triggered event handlers (button clicks, form changes, chat
messages, voice input) and the script execution engine live here.

UI widgets are accessed through the ``ui_refs`` module-level namespace
that is set by ``main.py`` after the UI is built.
"""

import json
import asyncio
import uuid
import wave
import re
import threading
import traceback
from datetime import datetime
from pathlib import Path

from nicegui import ui

import nav_runtime
from gemini_client import GeminiClient, ResponseType
from robot_discovery import (
    PLATFORM_INFO,
    load_robot_config,
    load_robot_firmware,
    build_and_set_prompt,
)
from settings import save_settings


# ── Module-level references (set by main.py after init) ──────────
# These are injected by main.py so handlers can access shared state.

robot = None          # RobotHAL instance
gemini = None         # GeminiClient instance
ui_refs = None        # SimpleNamespace of UI widget references
robots_dir = None     # Path to robots_firmware/
tts_dir = None        # Path to static/tts/
calibration = None    # dict with speed_seconds_per_foot, default_motor_speed
selected_robot = ""   # Currently selected robot name

# Chat state
chat_history: list[dict] = []
current_code: str = "# No navigation script loaded yet."

# Execution state
_running_task: asyncio.Task | None = None
_execution_lock = threading.Lock()
_voice_initiated: bool = False
_processing_voice: bool = False
_auto_action_done: bool = False


def init(*, robot_hal, gemini_client, refs, robots_firmware_dir,
         tts_audio_dir, cal, initial_robot, saved_settings):
    """Initialize module-level references.  Called once from main.py."""
    global robot, gemini, ui_refs, robots_dir, tts_dir
    global calibration, selected_robot, _saved
    robot = robot_hal
    gemini = gemini_client
    ui_refs = refs
    robots_dir = robots_firmware_dir
    tts_dir = tts_audio_dir
    calibration = cal
    selected_robot = initial_robot
    _saved = saved_settings


# ══════════════════════════════════════════════════════════════════
#  HELPERS
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


def _save_current_settings() -> None:
    """Persist all current settings to disk."""
    save_settings({
        "api_key": ui_refs.api_key_input.value.strip() if gemini.is_connected else _saved.get("api_key", ""),
        "model": ui_refs.model_select.value,
        "speed_seconds_per_foot": calibration["speed_seconds_per_foot"],
        "default_motor_speed": calibration["default_motor_speed"],
        "uart_port": ui_refs.port_select.value if ui_refs.port_select.value != "(no robot found)" else "",
        "uart_baud": ui_refs.baud_select.value,
        "robot": selected_robot,
    })


def _estimate_duration(code: str) -> float | None:
    """Estimate total duration of an ACTION script by summing wait() calls.

    Returns None for NAVIGATION scripts (contain while is_running()).
    """
    if "while" in code and ("is_running()" in code or "robot.is_running()" in code):
        return None
    total = 0.0
    for m in re.finditer(r'(?:robot\.)?wait\s*\(\s*([\d.]+)\s*\)', code):
        total += float(m.group(1))
    return total if total > 0 else None


def _set_go_stop_button(running: bool, replay: bool = False) -> None:
    """Toggle Go!/Stop/Go Again! button appearance."""
    btn = ui_refs.go_stop_button
    if running:
        btn.set_text("🛑 Stop")
        btn._classes = [c for c in btn._classes if c != 'fun-btn-primary']
        btn._classes.append('stop-btn')
        btn.update()
    else:
        btn.set_text("🔄 Go Again!" if replay else "🚀 Go!")
        btn._classes = [c for c in btn._classes if c != 'stop-btn']
        if 'fun-btn-primary' not in btn._classes:
            btn._classes.append('fun-btn-primary')
        btn.update()


def _reset_play_ui() -> None:
    """Reset progress animation and Go/Stop button."""
    _set_go_stop_button(False)
    ui.run_javascript("stopProgressAnimation()")


# ══════════════════════════════════════════════════════════════════
#  ROBOT & CONNECTION HANDLERS
# ══════════════════════════════════════════════════════════════════

def handle_robot_change(robot_name: str) -> None:
    """Handle switching to a different robot type."""
    global selected_robot
    selected_robot = robot_name

    config = load_robot_config(robots_dir, robot_name)
    firmware_src, firmware_file = load_robot_firmware(robots_dir, robot_name)
    platform = PLATFORM_INFO.get(
        config.get("firmware_platform", ""), PLATFORM_INFO.get("microbit")
    )

    # Update header badge
    ui_refs.robot_badge.set_content(
        f'<span class="robot-badge">🤖 {robot_name.capitalize()}</span>'
    )

    # Update settings platform label
    ui_refs.robot_platform_label.set_text(
        f"Type: {config.get('firmware_platform', '').upper()}"
    )

    # Update Firmware tab
    ui_refs.firmware_title.set_content(
        f'<div class="section-title" style="color: var(--primary);">'
        f'{platform["icon"]} {platform["label"]} Code</div>'
    )
    ui_refs.firmware_instructions.set_text(platform["copy_instructions"])
    ui_refs.firmware_code_display.set_content(
        f'<pre class="code-viewer" style="max-height: 500px;">'
        f'{_escape_html(firmware_src)}</pre>'
    )
    ui_refs.firmware_filename_label.set_text(f"📄 {firmware_file}")

    # Update mutable state so existing button lambdas read new values
    ui_refs.firmware_state["source"] = firmware_src
    ui_refs.firmware_state["open_url"] = platform["open_url"]

    # Update open-IDE button text
    ui_refs.firmware_open_btn.set_text(platform["open_label"])

    # Update Protocol Docs tab
    ui_refs.protocol_meta.set_text(
        f"Robot: {robot_name.capitalize()} · "
        f"Platform: {config.get('firmware_platform', '?')} · "
        f"Speed: {config.get('baud_rate', '?')}"
    )
    if config:
        ui_refs.protocol_table_html.set_content(_build_protocol_table(config))
    else:
        ui_refs.protocol_table_html.set_content(
            '<span style="color: var(--danger); font-size: 1.1rem;">⚠️ No commands found for this robot.</span>'
        )

    # Update baud rate to match robot config
    if config.get("baud_rate"):
        ui_refs.baud_select.value = config["baud_rate"]
        ui_refs.baud_select.update()

    ui_refs.status_label.set_text(f"Switched to {robot_name.capitalize()}! 🎉")
    ui.notify(f"🤖 Now talking to {robot_name.capitalize()}!", type="positive")

    # Rebuild the system prompt for the new robot
    build_and_set_prompt(robots_dir, robot_name, gemini, robot, calibration, nav_runtime)

    # Persist
    _save_current_settings()


def handle_emergency_stop() -> None:
    """Send emergency stop, kill running code, and update UI."""
    stop_execution()
    _reset_play_ui()
    try:
        robot.stop()
        ui.notify("🛑 Robot stopped!", type="negative", position="top")
    except ConnectionError:
        ui.notify("⚠️ Robot not plugged in — can't stop!", type="warning", position="top")
    ui_refs.status_label.set_text("🛑 STOPPED!")


def handle_connect() -> None:
    """Connect to the selected serial port."""
    port = ui_refs.port_select.value
    baud = ui_refs.baud_select.value
    if not port or port == "(no robot found)":
        ui.notify("Pick a USB port first!", type="warning")
        return
    try:
        robot.connect(port, baud)
        ui_refs.serial_status.set_text(f"✅ Plugged into {port}")
        ui_refs.connection_badge.set_content(
            '<span class="conn-badge conn-online">🚀 Robot is ready!</span>'
        )
        ui_refs.status_label.set_text("Robot plugged in! 🎉")
        ui.notify("✅ Robot connected!", type="positive")
        _save_current_settings()
    except Exception as e:
        ui_refs.serial_status.set_text(f"Oops! Something went wrong: {e}")
        ui.notify(f"❌ Couldn't connect: {e}", type="negative")


def handle_disconnect() -> None:
    """Disconnect from serial port."""
    stop_execution()
    robot.disconnect()
    ui_refs.serial_status.set_text("Not connected yet")
    ui_refs.connection_badge.set_content(
        '<span class="conn-badge conn-offline">😴 Robot is sleeping</span>'
    )
    ui_refs.status_label.set_text("Robot unplugged")
    ui.notify("Robot unplugged 👋", type="info")


def refresh_ports() -> None:
    """Refresh the list of available serial ports."""
    ports = robot.list_ports()
    ui_refs.port_select.options = ports if ports else ["(no robot found)"]
    ui_refs.port_select.value = ports[0] if ports else "(no robot found)"
    ui_refs.port_select.update()
    ui.notify(f"Found {len(ports)} robot(s)! 🔍", type="info")


# ══════════════════════════════════════════════════════════════════
#  VOICE HANDLERS
# ══════════════════════════════════════════════════════════════════

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
        _voice_initiated = True
        ui_refs.chat_input.value = text
        await send_chat_message()
    finally:
        _processing_voice = False


# ══════════════════════════════════════════════════════════════════
#  SETTINGS HANDLERS
# ══════════════════════════════════════════════════════════════════

def handle_model_change(label: str) -> None:
    """Handle switching the AI model."""
    gemini.model_label = label
    ui.notify(f"🧠 Switched to {label}", type="info")
    if gemini.is_connected:
        ui_refs.gemini_status.set_text(f"✅ AI brain is awake — using {label}")
    _save_current_settings()


def handle_calibration_change(key: str, value) -> None:
    """Handle calibration parameter change."""
    calibration[key] = value
    ui_refs.cal_status.set_text(
        f"📏 {calibration['speed_seconds_per_foot']} sec/foot · "
        f"🏎️ Motor speed: {calibration['default_motor_speed']}"
    )
    if selected_robot:
        build_and_set_prompt(robots_dir, selected_robot, gemini, robot, calibration, nav_runtime)
    ui.notify("⚙️ Calibration updated!", type="info")
    _save_current_settings()


async def save_api_key() -> None:
    """Save the Gemini API key and test the connection."""
    key = ui_refs.api_key_input.value.strip()
    if not key:
        ui.notify("Type in your AI key first!", type="warning")
        return

    ui_refs.gemini_status.set_text("⏳ Testing connection…")
    ui_refs.status_label.set_text("🧠 Connecting AI brain…")

    try:
        gemini.configure(api_key=key)
        if selected_robot:
            build_and_set_prompt(robots_dir, selected_robot, gemini, robot, calibration, nav_runtime)
        test_reply = await gemini.test_connection()
        ui_refs.gemini_status.set_text(
            f"✅ AI brain is awake! Model: {gemini.model_label}"
        )
        ui_refs.status_label.set_text("✨ AI brain activated!")
        ui.notify("🧠 AI brain activated! Connection works.", type="positive")
        _save_current_settings()
    except Exception as exc:
        error = str(exc)
        ui_refs.gemini_status.set_text(f"❌ Connection failed: {error[:80]}")
        ui_refs.status_label.set_text("⚠️ AI connection failed")
        ui.notify(f"❌ Could not connect: {error[:120]}", type="negative")


# ══════════════════════════════════════════════════════════════════
#  CHAT
# ══════════════════════════════════════════════════════════════════

async def send_chat_message() -> None:
    """Handle sending a chat message with intent classification."""
    global current_code, _voice_initiated
    text = ui_refs.chat_input.value.strip()
    if not text:
        return
    ui_refs.chat_input.value = ""

    now = datetime.now().strftime("%H:%M")

    # User message
    with ui_refs.chat_container:
        ui.html(
            f'<div class="chat-msg chat-user">'
            f"{_escape_html(text)}"
            f'<div class="chat-time">{now}</div></div>'
        )
    await ui.run_javascript(
        "document.getElementById('chat-scroll-container').scrollTop = "
        "document.getElementById('chat-scroll-container').scrollHeight"
    )

    ui_refs.status_label.set_text("🤖 Robot is thinking…")
    await ui.run_javascript("setRobotFaceState('thinking')")

    try:
        response = await gemini.send_message(text)
        parsed = GeminiClient.parse_response(response)
        display_text = GeminiClient.clean_message_for_display(response)

        with ui_refs.chat_container:
            ui.html(
                f'<div class="chat-msg chat-assistant">'
                f"{_escape_html(display_text)}"
                f'<div class="chat-time">{now}</div></div>'
            )
        await ui.run_javascript(
            "document.getElementById('chat-scroll-container').scrollTop = "
            "document.getElementById('chat-scroll-container').scrollHeight"
        )

        # Speak the response aloud if voice-initiated
        if _voice_initiated and display_text.strip():
            _voice_initiated = False
            try:
                pcm_data = await gemini.synthesize_speech(display_text)
                if pcm_data:
                    audio_id = uuid.uuid4().hex
                    wav_path = tts_dir / f'{audio_id}.wav'
                    with wave.open(str(wav_path), 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(24000)
                        wf.writeframes(pcm_data)
                    audio_url = f'/static/tts/{audio_id}.wav'
                    await ui.run_javascript(f"playGeminiAudio('{audio_url}')")

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
            ui_refs.code_display.value = parsed.code
            ui_refs.code_expansion.open()

            if parsed.response_type == ResponseType.ACTION:
                await ui.run_javascript("setRobotFaceState('idle')")
                ui_refs.status_label.set_text("🚀 Running action…")
                await _execute_code_async(parsed.code, mode="action", auto_launched=True)
            elif parsed.response_type == ResponseType.NAVIGATION:
                await ui.run_javascript("setRobotFaceState('idle')")
                ui_refs.status_label.set_text("📋 Navigation ready — press Go! to start")
                ui.notify(
                    "🧭 Navigation script ready! Press 🚀 Go! to start.",
                    type="info",
                )
        else:
            if not _voice_initiated:
                await ui.run_javascript("setRobotFaceState('idle')")
            ui_refs.status_label.set_text("✨ Ready to play!")
    except Exception:
        await ui.run_javascript("setRobotFaceState('idle')")
        ui_refs.status_label.set_text("✨ Ready to play!")
        raise


# ══════════════════════════════════════════════════════════════════
#  SCRIPT EXECUTION
# ══════════════════════════════════════════════════════════════════

async def _execute_code_async(code: str, mode: str = "action", auto_launched: bool = False) -> None:
    """Execute generated Python code in a background task."""
    global _running_task, _auto_action_done

    stop_execution()
    nav_runtime.running = True
    _auto_action_done = False
    _set_go_stop_button(True)
    ui_refs.code_display.value = code

    if mode == "navigation":
        await ui.run_javascript("startIndeterminateProgress()")
    else:
        duration = _estimate_duration(code)
        if duration and duration > 0:
            await ui.run_javascript(f"startDeterminateProgress({duration})")
        else:
            await ui.run_javascript("startIndeterminateProgress()")

    _was_cancelled = False
    _error_occurred = False
    _error_line = None
    _error_type = None
    _error_msg = None

    async def _run():
        nonlocal _error_occurred, _error_line, _error_type, _error_msg
        try:
            exec_globals = {
                "robot": nav_runtime.robot,
                "send": nav_runtime.send,
                "read": nav_runtime.read,
                "stop": nav_runtime.stop,
                "wait": nav_runtime.wait,
                "is_running": nav_runtime.is_running,
                "__builtins__": __builtins__,
            }
            compiled = compile(code, '<user_script>', 'exec')
            await asyncio.to_thread(exec, compiled, exec_globals)
        except Exception as exc:
            _error_occurred = True
            _error_type = type(exc).__name__
            _error_msg = str(exc)
            tb = traceback.extract_tb(exc.__traceback__)
            for entry in reversed(tb):
                if entry.filename == '<user_script>':
                    _error_line = entry.lineno
                    break

    _running_task = asyncio.create_task(_run())

    try:
        await _running_task
    except asyncio.CancelledError:
        _was_cancelled = True
    finally:
        nav_runtime.running = False
        ui.run_javascript("stopProgressAnimation()")
        ui.run_javascript("setRobotFaceState('idle')")
        if _error_occurred:
            _set_go_stop_button(False)
            ui_refs.code_display.value = code
            ui_refs.code_expansion.open()
            ui_refs.status_label.set_text("⚠️ Script error")
            if _error_line:
                notify_msg = f"⚠️ Line {_error_line}: {_error_type} — {_error_msg}"
            else:
                notify_msg = f"⚠️ {_error_type} — {_error_msg}"
            ui.notify(notify_msg, type="negative", duration=8)
            now = datetime.now().strftime("%H:%M")
            if _error_line:
                err_html = (
                    f'<div class="chat-msg chat-assistant" style="border-left: 3px solid var(--danger);">'
                    f'🐛 <b>Script Error</b><br>'
                    f'{_escape_html(_error_type)} on line {_error_line}: '
                    f'{_escape_html(_error_msg)}'
                    f'<div class="chat-time">{now}</div></div>'
                )
            else:
                err_html = (
                    f'<div class="chat-msg chat-assistant" style="border-left: 3px solid var(--danger);">'
                    f'🐛 <b>Script Error</b><br>'
                    f'{_escape_html(_error_type)}: {_escape_html(_error_msg)}'
                    f'<div class="chat-time">{now}</div></div>'
                )
            with ui_refs.chat_container:
                ui.html(err_html)
        elif auto_launched and mode == "action" and not _was_cancelled:
            _auto_action_done = True
            _set_go_stop_button(False, replay=True)
            ui_refs.status_label.set_text("✅ Done! Press Go! to repeat")
        else:
            _set_go_stop_button(False)
            ui_refs.status_label.set_text("✨ Ready to play!")


def stop_execution() -> None:
    """Stop any running navigation code and speech."""
    global _running_task
    nav_runtime.running = False
    if _running_task and not _running_task.done():
        _running_task.cancel()
    _running_task = None
    ui.run_javascript("stopSpeaking()")


async def toggle_go_stop() -> None:
    """Toggle between Go! and Stop based on execution state."""
    if nav_runtime.running:
        stop_execution()
        _reset_play_ui()
        try:
            robot.stop()
        except ConnectionError:
            pass
        ui_refs.status_label.set_text("🛑 Stopped!")
        ui.notify("🛑 Script stopped!", type="negative")
    else:
        await execute_code()


async def execute_code() -> None:
    """Execute the current navigation script (triggered by Go! button)."""
    global _auto_action_done
    code_to_run = ui_refs.code_display.value
    if "No navigation script" in code_to_run:
        ui.notify("Tell the robot what to do first! 💬", type="warning")
        return
    mode = "navigation" if ("while" in code_to_run and "is_running()" in code_to_run) else "action"
    is_replay = _auto_action_done
    _auto_action_done = False
    await _execute_code_async(code_to_run, mode=mode, auto_launched=is_replay)


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
    ui_refs.code_display.value = current_code
    ui_refs.status_label.set_text("✨ Ready to play!")
    ui.run_javascript("stopSpeaking()")
