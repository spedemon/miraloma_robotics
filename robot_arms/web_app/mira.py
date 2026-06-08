"""
Mira Swarm Controller — Web Server

Flask + SocketIO backend that bridges the browser UI to the master
ESP32-C3 node via USB serial. Provides:
  - Real-time robot discovery and status via WebSocket
  - Command routing (single robot or broadcast)
  - Persistent robot name storage (robot_names.json)
  - Serial port auto-detection and runtime switching
"""

import os
import json
import re
import time
import threading
from datetime import datetime

import serial
import serial.tools.list_ports
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BAUD_RATE = 115200
NAMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "robot_names.json")
AUTOSAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sequence_autosave.json")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder=STATIC_DIR)
app.config["SECRET_KEY"] = "mira-swarm-2026"
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # No static file caching during dev
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ---------------------------------------------------------------------------
# Serial state
# ---------------------------------------------------------------------------

serial_lock = threading.Lock()
ser = None          # serial.Serial instance or None
serial_port = None  # current port name
serial_thread = None
serial_running = False

# Device type: "master" (master_mcu with swarm) or "robot" (single robotarm_mcu)
device_type = "master"

# ---------------------------------------------------------------------------
# Robot registry (server-side mirror of what master reports)
# ---------------------------------------------------------------------------

robots = {}  # MAC -> { "name": str, "mac": str, "online": bool, "lastSeen": float }

# Periodic poll timer
swarm_poll_timer = None
SWARM_POLL_INTERVAL = 5  # seconds

# ---------------------------------------------------------------------------
# Persistent name map
# ---------------------------------------------------------------------------

def load_names():
    """Load MAC→display-name map from disk."""
    if os.path.exists(NAMES_FILE):
        try:
            with open(NAMES_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}

def save_names(names):
    """Persist MAC→display-name map to disk."""
    with open(NAMES_FILE, "w") as f:
        json.dump(names, f, indent=2)

name_map = load_names()  # { "AA:BB:CC:DD:EE:FF": "Lefty", ... }

# ---------------------------------------------------------------------------
# Serial port helpers
# ---------------------------------------------------------------------------

def list_serial_ports():
    """Return list of available serial ports with metadata."""
    ports = []
    for p in serial.tools.list_ports.comports():
        ports.append({
            "device": p.device,
            "description": p.description,
            "hwid": p.hwid,
        })
    return ports

def auto_detect_port():
    """Try to find the master ESP32-C3 port automatically."""
    for p in serial.tools.list_ports.comports():
        # Prefer /dev/cu. ports on macOS (avoid /dev/tty. for writes)
        desc = (p.description or "").lower()
        if "usbmodem" in p.device.lower() or "esp" in desc or "cp210" in desc:
            return p.device
    # Fallback: return first available port
    ports = serial.tools.list_ports.comports()
    if ports:
        return ports[0].device
    return None

# ---------------------------------------------------------------------------
# Serial I/O
# ---------------------------------------------------------------------------

def serial_write(text):
    """Send a text command to the master MCU (thread-safe)."""
    global ser
    with serial_lock:
        if ser and ser.is_open:
            try:
                ser.write((text + "\n").encode("utf-8"))
                ser.flush()
                return True
            except serial.SerialException:
                return False
    return False

def serial_reader():
    """Background thread: reads serial lines and dispatches events."""
    global ser, serial_running, robots

    while serial_running:
        try:
            with serial_lock:
                if not ser or not ser.is_open:
                    break
                if ser.in_waiting == 0:
                    pass
                else:
                    pass

            # Read outside the lock to avoid blocking writes
            if ser and ser.is_open:
                try:
                    line = ser.readline()
                except serial.SerialException:
                    break
                if not line:
                    time.sleep(0.01)
                    continue

                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not text:
                    continue

                process_serial_line(text)
            else:
                break
        except Exception:
            time.sleep(0.05)
            continue

    serial_running = False
    socketio.emit("serial_status", {"connected": False, "port": None})

def process_serial_line(text):
    """Parse a serial line and emit the appropriate WebSocket events."""
    global robots, name_map, device_type

    timestamp = datetime.now().strftime("%H:%M:%S")

    # --- Device-type detection from startup banner ---
    # Detect robotarm_mcu by its unique banner lines
    if "Mira Motor MCU" in text:
        _switch_device_type("robot")
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # Detect and auto-register robot from its swarm node MAC line
    m = re.match(r"\[Swarm\] Node MAC:\s+([0-9A-Fa-f:]{17})", text)
    if m:
        mac = m.group(1).upper()
        _switch_device_type("robot")
        _register_direct_robot(mac)
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # Detect master_mcu by its unique banner
    if "Mira Master MCU" in text:
        _switch_device_type("master")
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # Fallback detection from prompt (when device was already booted)
    if text.strip() == "mira>" and device_type != "robot":
        _switch_device_type("robot")
        # Send 'id' command to get the MAC address for registration
        serial_write("id")
        return

    # Parse ID response from the 'id' command
    m = re.match(r"ID:\s+([0-9A-Fa-f:]{17})", text)
    if m and device_type == "robot":
        mac = m.group(1).upper()
        if mac not in robots:
            _register_direct_robot(mac)
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # --- Custom gesture protocol responses ---

    # SEQ_SAVE_OK <name> <count> [<loop>]
    m = re.match(r"SEQ_SAVE_OK\s+(\S+)\s+(\d+)(?:\s+(0|1))?", text)
    if m:
        name, count = m.group(1), int(m.group(2))
        loop = m.group(3) != "0" if m.group(3) else True  # default to looping
        socketio.emit("upload_result", {"ok": True, "name": name, "count": count, "loop": loop})
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # SEQ_SAVE_ERR <code> <reason>
    m = re.match(r"SEQ_SAVE_ERR\s+(\d+)\s+(.*)", text)
    if m:
        code, reason = int(m.group(1)), m.group(2)
        socketio.emit("upload_result", {"ok": False, "code": code, "reason": reason})
        socketio.emit("console_line", {"text": text, "type": "error", "time": timestamp})
        return

    # SEQ_LIST <count> [name1 name2 ...]
    m = re.match(r"SEQ_LIST\s+(\d+)(.*)", text)
    if m:
        count = int(m.group(1))
        names = m.group(2).strip().split() if m.group(2).strip() else []
        socketio.emit("custom_gestures", {"count": count, "names": names})
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # SEQ_DELETE_OK <name>
    m = re.match(r"SEQ_DELETE_OK\s+(\S+)", text)
    if m:
        socketio.emit("delete_result", {"ok": True, "name": m.group(1)})
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # SEQ_DELETE_ERR <name> <reason>
    m = re.match(r"SEQ_DELETE_ERR\s+(\S+)\s+(.*)", text)
    if m:
        socketio.emit("delete_result", {"ok": False, "name": m.group(1), "reason": m.group(2)})
        socketio.emit("console_line", {"text": text, "type": "error", "time": timestamp})
        return

    # SEQ_COUNT <count>
    m = re.match(r"SEQ_COUNT\s+(\d+)", text)
    if m:
        socketio.emit("staging_count", {"count": int(m.group(1))})
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # --- NEW_ROBOT: R1 [AA:BB:CC:DD:EE:FF] ---
    m = re.match(r"NEW_ROBOT:\s+(\S+)\s+\[([0-9A-Fa-f:]{17})\]", text)
    if m:
        master_name = m.group(1)
        mac = m.group(2).upper()
        display_name = name_map.get(mac, mac)

        robots[mac] = {
            "name": display_name,
            "masterName": master_name,
            "mac": mac,
            "online": True,
            "lastSeen": time.time(),
        }

        # If we have a stored name and the master's name differs, send rename
        if mac in name_map and name_map[mac] != master_name:
            serial_write(f"swarm rename {master_name} {name_map[mac]}")

        socketio.emit("robot_list", get_robot_list())
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # --- ROBOT_ONLINE: R1 [AA:BB:CC:DD:EE:FF] ---
    m = re.match(r"ROBOT_ONLINE:\s+(\S+)\s+\[([0-9A-Fa-f:]{17})\]", text)
    if m:
        master_name = m.group(1)
        mac = m.group(2).upper()
        display_name = name_map.get(mac, mac)

        robots[mac] = {
            "name": display_name,
            "masterName": master_name,
            "mac": mac,
            "online": True,
            "lastSeen": time.time(),
        }

        # If we have a stored name and the master's name differs, send rename
        if mac in name_map and name_map[mac] != master_name:
            serial_write(f"swarm rename {master_name} {name_map[mac]}")

        socketio.emit("robot_list", get_robot_list())
        socketio.emit("console_line", {"text": text, "type": "system", "time": timestamp})
        return

    # --- [Swarm] RX went offline ---
    m = re.match(r"\[Swarm\]\s+(\S+)\s+went offline", text)
    if m:
        robot_name = m.group(1)
        for mac, robot in robots.items():
            if robot.get("masterName") == robot_name or robot.get("name") == robot_name:
                robot["online"] = False
                break
        socketio.emit("robot_list", get_robot_list())
        socketio.emit("console_line", {"text": text, "type": "warning", "time": timestamp})
        return

    # --- Robot replies: R1> OK — ... ---
    m = re.match(r"(\S+)>\s+(.*)", text)
    if m:
        reply_body = m.group(2)
        socketio.emit("console_line", {"text": text, "type": "response", "time": timestamp})
        # Re-process structured protocol responses (SEQ_*)
        if reply_body.startswith("SEQ_"):
            process_serial_line(reply_body)
        return

    # --- Command echo: [→ ALL] ... or [→ R1] ... ---
    m = re.match(r"\[→\s+(.+?)\]\s+(.*)", text)
    if m:
        socketio.emit("console_line", {"text": text, "type": "command", "time": timestamp})
        return

    # --- Swarm list output ---
    if text.startswith("  ") and ("online" in text or "s ago" in text or "OFFLINE" in text):
        # Parse swarm list line:  R1        AA:BB:CC:DD:EE:FF  online
        parts = text.split()
        if len(parts) >= 3:
            master_name = parts[0]
            mac_candidate = parts[1]
            if re.match(r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}", mac_candidate):
                mac = mac_candidate.upper()
                is_online = "online" in text and "OFFLINE" not in text
                display_name = name_map.get(mac, mac)

                robots[mac] = {
                    "name": display_name,
                    "masterName": master_name,
                    "mac": mac,
                    "online": is_online,
                    "lastSeen": time.time() if is_online else robots.get(mac, {}).get("lastSeen", 0),
                }

        # Don't echo poll data lines to console (they fire every 5s)
        socketio.emit("robot_list", get_robot_list())
        return

    # --- Generic output ---
    # Filter out prompt lines, decorative lines, and echoed poll commands
    stripped = text.strip()
    if stripped in ("master>", "") or text.startswith("════") or text.startswith("────"):
        return
    if stripped.startswith("swarm ") or stripped.startswith("Swarm"):
        return  # Echoed poll command or swarm list title
    if stripped.startswith("Waiting for robots"):
        return  # Startup message

    socketio.emit("console_line", {"text": text, "type": "info", "time": timestamp})

def get_robot_list():
    """Return sorted list of robots for the frontend (online first, then alphabetical)."""
    return sorted(robots.values(),
                  key=lambda r: (not r.get("online", False), r.get("masterName", r["mac"])))

# ---------------------------------------------------------------------------
# Serial connection management
# ---------------------------------------------------------------------------

def start_swarm_poll():
    """Start the periodic swarm list poll timer (master mode only)."""
    global swarm_poll_timer
    stop_swarm_poll()

    if device_type != "master":
        return  # No swarm polling in direct robot mode

    def poll():
        global swarm_poll_timer
        while serial_running:
            time.sleep(SWARM_POLL_INTERVAL)
            if serial_running and device_type == "master":
                serial_write("swarm list")

    swarm_poll_timer = threading.Thread(target=poll, daemon=True)
    swarm_poll_timer.start()

def stop_swarm_poll():
    """Stop the periodic swarm list poll timer."""
    global swarm_poll_timer
    swarm_poll_timer = None  # Thread will exit on next iteration check


def _switch_device_type(new_type):
    """Switch between 'master' and 'robot' device modes."""
    global device_type, robots
    if device_type == new_type:
        return
    device_type = new_type
    print(f"  🔄 Device type detected: {new_type}")
    socketio.emit("device_type", {"type": new_type})

    if new_type == "robot":
        stop_swarm_poll()
        # Clear any pre-populated or leftover robots from master mode
        robots = {}
        socketio.emit("robot_list", get_robot_list())
    elif new_type == "master":
        # Re-populate known robots from name_map as offline
        robots = {}
        for mac, display_name in name_map.items():
            robots[mac] = {
                "name": display_name,
                "masterName": display_name,
                "mac": mac,
                "online": False,
                "lastSeen": 0,
            }
        socketio.emit("robot_list", get_robot_list())
        start_swarm_poll()


def _register_direct_robot(mac):
    """Auto-register a directly-connected robotarm_mcu."""
    global robots
    display_name = name_map.get(mac, mac)
    robots[mac] = {
        "name": display_name,
        "masterName": display_name,
        "mac": mac,
        "online": True,
        "lastSeen": time.time(),
    }
    socketio.emit("robot_list", get_robot_list())
    print(f"  🤖 Direct robot registered: {display_name} [{mac}]")


def connect_serial(port):
    """Open a serial connection to the given port."""
    global ser, serial_port, serial_thread, serial_running, device_type, robots

    disconnect_serial()

    # Reset device type and robot list — will be re-populated after detection
    device_type = "master"
    robots = {}

    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
        serial_port = port
        serial_running = True
        serial_thread = threading.Thread(target=serial_reader, daemon=True)
        serial_thread.start()

        socketio.emit("serial_status", {"connected": True, "port": port})
        socketio.emit("device_type", {"type": device_type})

        # Wait for banner lines to arrive and trigger auto-detection.
        # Then request robot list from master (if it is a master).
        def _deferred_init():
            # Send a newline to trigger a prompt for fallback detection
            # (if the device was already booted, banner has passed)
            time.sleep(0.3)
            serial_write("")
            time.sleep(1.2)  # Allow banner/prompt to arrive and be parsed
            if device_type == "master" and serial_running:
                # Re-populate known robots as offline for master mode
                for mac, display_name in name_map.items():
                    if mac not in robots:
                        robots[mac] = {
                            "name": display_name,
                            "masterName": display_name,
                            "mac": mac,
                            "online": False,
                            "lastSeen": 0,
                        }
                socketio.emit("robot_list", get_robot_list())
                serial_write("swarm list")
                start_swarm_poll()

        threading.Thread(target=_deferred_init, daemon=True).start()

        return True
    except serial.SerialException as e:
        ser = None
        serial_port = None
        socketio.emit("serial_status", {"connected": False, "port": None, "error": str(e)})
        return False

def disconnect_serial():
    """Close the current serial connection."""
    global ser, serial_port, serial_running, robots

    serial_running = False
    stop_swarm_poll()
    if serial_thread:
        serial_thread.join(timeout=2)

    with serial_lock:
        if ser and ser.is_open:
            try:
                ser.close()
            except Exception:
                pass
        ser = None
        serial_port = None

    # Clear all robots when serial is disconnected
    robots = {}
    socketio.emit("robot_list", get_robot_list())

# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route("/api/robots")
def api_robots():
    return jsonify(get_robot_list())

@app.route("/api/robots/rename", methods=["POST"])
def api_rename():
    data = request.json
    mac = data.get("mac", "").upper()
    new_name = data.get("name", "").strip()

    if not mac or not new_name:
        return jsonify({"error": "mac and name required"}), 400

    if len(new_name) > 15:
        return jsonify({"error": "Name too long (max 15 chars)"}), 400

    # Find current master-side name for this robot
    robot = robots.get(mac)
    if not robot:
        return jsonify({"error": "Robot not found"}), 404

    old_master_name = robot.get("masterName", robot.get("name"))

    # Send rename command to master (only in master mode)
    if device_type == "master":
        serial_write(f"swarm rename {old_master_name} {new_name}")

    # Update local state
    robot["name"] = new_name
    robot["masterName"] = new_name
    name_map[mac] = new_name
    save_names(name_map)

    socketio.emit("robot_list", get_robot_list())
    return jsonify({"ok": True})

@app.route("/api/serial/ports")
def api_serial_ports():
    return jsonify({
        "ports": list_serial_ports(),
        "current": serial_port,
        "connected": ser is not None and ser.is_open,
    })

@app.route("/api/serial/connect", methods=["POST"])
def api_serial_connect():
    data = request.json
    port = data.get("port")
    if not port:
        return jsonify({"error": "port required"}), 400

    ok = connect_serial(port)
    return jsonify({"ok": ok, "port": port})

@app.route("/api/serial/disconnect", methods=["POST"])
def api_serial_disconnect():
    disconnect_serial()
    socketio.emit("serial_status", {"connected": False, "port": None})
    return jsonify({"ok": True})

@app.route("/api/sequence/autosave", methods=["POST"])
def api_sequence_autosave():
    data = request.json
    with open(AUTOSAVE_FILE, "w") as f:
        json.dump(data, f)
    return jsonify({"ok": True})

@app.route("/api/sequence/autoload", methods=["GET"])
def api_sequence_autoload():
    if os.path.exists(AUTOSAVE_FILE):
        try:
            with open(AUTOSAVE_FILE, "r") as f:
                return jsonify(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return jsonify({"keyframes": []})

# ---------------------------------------------------------------------------
# WebSocket events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def ws_connect():
    """Send initial state to newly connected client."""
    connected = ser is not None and ser.is_open
    emit("serial_status", {"connected": connected, "port": serial_port})
    emit("robot_list", get_robot_list())
    emit("device_type", {"type": device_type})

@socketio.on("send_command")
def ws_send_command(data):
    """
    Receive a command from the browser and forward to serial.
    data: { "target": "all" | "<robot_name>", "command": "<cmd_string>" }
    """
    target = data.get("target", "all")
    command = data.get("command", "").strip()
    if not command:
        return

    if device_type == "robot":
        # Direct connection: always send raw command (no @target prefix)
        serial_write(command)
    elif target == "all":
        serial_write(command)
    else:
        serial_write(f"@{target} {command}")

@socketio.on("request_robot_list")
def ws_request_robot_list():
    """Client requests a fresh robot list from the master."""
    if device_type == "master":
        serial_write("swarm list")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("═══════════════════════════════════════════")
    print("  Mira Swarm Controller — Web Server")
    print("═══════════════════════════════════════════")
    print()

    # Auto-detect and connect to serial port
    port = auto_detect_port()
    if port:
        print(f"  Auto-detected serial port: {port}")
        if connect_serial(port):
            print(f"  ✅ Connected to {port}")
        else:
            print(f"  ⚠️  Failed to connect to {port}")
            print("  Use the UI to select a different port.")
    else:
        print("  ⚠️  No serial ports detected.")
        print("  Connect the master ESP32-C3 and use the UI to configure.")

    print()
    print("  Open http://localhost:5050 in your browser")
    print()

    socketio.run(app, host="0.0.0.0", port=5050, debug=False, allow_unsafe_werkzeug=True)
