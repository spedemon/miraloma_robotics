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
from urllib.parse import unquote
from datetime import datetime

import serial
import serial.tools.list_ports
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit

from app_paths import resource_path, user_data_dir
from board_inspector import BoardInspector
from device_manager import DeviceManager, DeviceSession
from firmware_update import FirmwareCatalog, FirmwareUpdater
from ble_manager import BleManager
from instance_lock import InstanceLock

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BAUD_RATE = 115200
DATA_DIR = user_data_dir()
NAMES_FILE = DATA_DIR / "robot_names.json"
AUTOSAVE_FILE = DATA_DIR / "sequence_autosave.json"
STATIC_DIR = resource_path("static")

# Development builds historically stored mutable files beside mira.py. Read
# them once as a migration fallback, but always write to the user-data folder.
LEGACY_NAMES_FILE = resource_path("robot_names.json")
LEGACY_AUTOSAVE_FILE = resource_path(".sequence_autosave.json")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder=str(STATIC_DIR))
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
device_manager = None
firmware_catalog = FirmwareCatalog()
firmware_updater = None
ble_manager = None

# Periodic poll timer
swarm_poll_timer = None
SWARM_POLL_INTERVAL = 5  # seconds

# ---------------------------------------------------------------------------
# Persistent name map
# ---------------------------------------------------------------------------

def load_names():
    """Load MAC→display-name map from disk."""
    candidates = [NAMES_FILE]
    if LEGACY_NAMES_FILE != NAMES_FILE:
        candidates.append(LEGACY_NAMES_FILE)
    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}

def save_names(names):
    """Persist MAC→display-name map to disk."""
    with NAMES_FILE.open("w", encoding="utf-8") as f:
        json.dump(names, f, indent=2)

name_map = load_names()  # { "AA:BB:CC:DD:EE:FF": "Lefty", ... }
name_migrations = set()

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
    """Try to find an ESP32 or USB serial adapter automatically."""
    for p in serial.tools.list_ports.comports():
        # Prefer /dev/cu. ports on macOS (avoid /dev/tty. for writes)
        device = (p.device or "").lower()
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        known_usb_serial = any(token in device or token in desc or token in hwid for token in (
            "usbmodem",
            "usbserial",
            "esp32",
            "espressif",
            "cp210",
            "ch340",
            "ch910",
        ))
        if known_usb_serial or p.vid is not None:
            return p.device
    # Do not silently connect to Bluetooth, debug-console, or unrelated ports.
    # The UI still lists every port for manual selection.
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


def _emit_calibration_values(body, target=None):
    """Publish a cal_get reply as structured values for the calibration UI."""
    match = re.search(
        r"Calibration:\s+B=(-?\d+(?:\.\d+)?)\s+S=(-?\d+(?:\.\d+)?)\s+"
        r"E=(-?\d+(?:\.\d+)?)\s+G=(-?\d+(?:\.\d+)?)",
        body,
    )
    if not match:
        return False

    payload = dict(zip(("base", "shoulder", "elbow", "grip"), map(float, match.groups())))
    if target:
        payload["target"] = target
    socketio.emit("calibration_values", payload)
    return True

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
    # The console prompt has no trailing newline, so this startup message may
    # arrive as "mira> [Swarm] Node MAC: ...".
    m = re.search(r"\[Swarm\] Node MAC:\s+([0-9A-Fa-f:]{17})", text)
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
        display_name = name_map.get(mac, master_name)

        robots[mac] = {
            "name": display_name,
            "masterName": master_name,
            "mac": mac,
            "online": True,
            "lastSeen": time.time(),
        }

        # Migrate names saved by older app versions into upgraded robot firmware.
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
        display_name = name_map.get(mac, master_name)

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
        target, reply_body = m.groups()
        _emit_calibration_values(reply_body, target)
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

    _emit_calibration_values(text)
    socketio.emit("console_line", {"text": text, "type": "info", "time": timestamp})

def get_robot_list():
    """Return sorted list of robots for the frontend (online first, then alphabetical)."""
    public = []
    for robot in robots.values():
        item = {key: value for key, value in robot.items() if key != "endpoints"}
        endpoints = robot.get("endpoints", {})
        transports = {endpoint["transport"] for endpoint in endpoints.values()}
        labels = {"usb": "USB", "ble": "Bluetooth", "wireless": "Wireless"}
        item["connection"] = " + ".join(
            labels[value] for value in ("usb", "ble", "wireless") if value in transports
        ) or None
        item["online"] = bool(endpoints) and any(e.get("online", True) for e in endpoints.values())
        public.append(item)
    return sorted(public,
                  key=lambda r: (not r.get("online", False), r.get("masterName", r["mac"])))


def _upsert_endpoint(mac, endpoint_key, endpoint, **fields):
    """Merge one physical/wireless path into the MAC-keyed robot registry."""
    global robots
    mac = mac.upper()
    is_new = mac not in robots
    robot = robots.setdefault(mac, {
        "name": name_map.get(mac, mac), "masterName": fields.get("masterName", mac),
        "mac": mac, "lastSeen": time.time(), "firmware": None, "legacy": False,
        "endpoints": {},
    })
    changed = is_new or robot["endpoints"].get(endpoint_key) != endpoint
    robot["endpoints"][endpoint_key] = endpoint
    robot["lastSeen"] = time.time()
    for key, value in fields.items():
        if value is not None:
            changed = changed or robot.get(key) != value
            robot[key] = value
    device_name = fields.get("name")
    if device_name:
        robot["name"] = device_name
        if name_map.get(mac) != device_name:
            name_map[mac] = device_name
            save_names(name_map)
    elif not robot.get("name") or robot.get("name") == mac:
        robot["name"] = name_map.get(mac, mac)
    if changed:
        socketio.emit("robot_list", get_robot_list())


def _prune_missing_sessions():
    live_ports = set()
    if device_manager:
        live_ports.update(session.port.device for session in device_manager.connected_sessions())
    if ble_manager:
        live_ports.update(session.port.device for session in ble_manager.connected_sessions())
    changed = False
    for mac in list(robots):
        endpoints = robots[mac].setdefault("endpoints", {})
        for key in list(endpoints):
            if endpoints[key].get("port") not in live_ports:
                del endpoints[key]
                changed = True
        if not endpoints:
            robots[mac]["online"] = False
    if changed:
        socketio.emit("robot_list", get_robot_list())


def _migrate_local_name(mac):
    """Write a legacy app-local alias to upgraded robot flash once."""
    mac = mac.upper()
    legacy_name = name_map.get(mac)
    if not legacy_name or legacy_name == mac or mac in name_migrations:
        return
    if _route_command(mac, f"name set {legacy_name}"):
        name_migrations.add(mac)


def _device_state_changed():
    """Reconcile USB/BLE sessions and publish one complete UI snapshot."""
    _prune_missing_sessions()
    if device_manager:
        for session in device_manager.connected_sessions():
            info = session.info
            if info.role == "robot":
                _upsert_endpoint(
                    info.device_id, f"usb:{session.port.device}",
                    {"transport": "usb", "port": session.port.device, "online": True},
                    firmware=info.firmware, legacy=info.legacy, name=info.name,
                )
                if not info.name:
                    _migrate_local_name(info.device_id)
            elif info.role == "wireless_controller":
                session.write("swarm list")
    if ble_manager:
        for session in ble_manager.connected_sessions():
            info = session.info
            _upsert_endpoint(
                info.device_id, f"ble:{session.address}",
                {"transport": "ble", "port": session.port.device, "online": True},
                firmware=info.firmware, legacy=info.legacy, name=info.name,
            )
            if not info.name:
                _migrate_local_name(info.device_id)
    devices = _device_snapshot()
    socketio.emit("device_inventory", {"devices": devices})
    socketio.emit("serial_status", {"connected": bool([d for d in devices if d["state"] == "connected"])})


def _device_snapshot():
    devices = device_manager.snapshot() if device_manager else []
    if ble_manager:
        devices.extend(ble_manager.snapshot())
    for device in devices:
        robot = robots.get(device.get("deviceId"))
        device["name"] = robot.get("name") if robot else None
    return devices


def _managed_line(session: DeviceSession, text: str):
    """Parse output in the context of the USB or BLE device that produced it."""
    info = session.info
    if info and info.role == "robot" and info.device_id != "pending":
        transport = "ble" if session.port.device.startswith("ble:") else "usb"
        _upsert_endpoint(
            info.device_id, f"{transport}:{session.port.device}",
            {"transport": transport, "port": session.port.device, "online": True},
            firmware=info.firmware, legacy=info.legacy, name=info.name,
        )

    # Machine-readable controller events from new firmware.
    event = re.search(r"MIRA_EVENT\s+ROBOT\s+(.+)$", text)
    if event and info and info.role == "wireless_controller":
        values = dict(re.findall(r"([a-z_]+)=([^\s]+)", event.group(1)))
        mac = values.get("id")
        if mac:
            key = f"wireless:{session.port.device}"
            if values.get("online", "1") == "0":
                robot = robots.get(mac.upper())
                if robot:
                    robot.get("endpoints", {}).pop(key, None)
                    robot["online"] = bool(robot.get("endpoints"))
                    socketio.emit("robot_list", get_robot_list())
            else:
                _upsert_endpoint(
                    mac, key,
                    {"transport": "wireless", "port": session.port.device, "online": True},
                    masterName=unquote(values.get("name", mac)),
                    name=(unquote(values["name"])
                          if values.get("name") and values.get("named", "1") == "1"
                          else None),
                    firmware=values.get("firmware"),
                    legacy=values.get("protocol", "0") == "0",
                )
                if values.get("named") == "0":
                    _migrate_local_name(mac)
        return

    # Legacy master events remain supported during development.
    match = re.match(r"(?:NEW_ROBOT|ROBOT_ONLINE):\s+(\S+)\s+\[([0-9A-Fa-f:]{17})\]", text)
    if match and info and info.role == "wireless_controller":
        _upsert_endpoint(
            match.group(2), f"wireless:{session.port.device}",
            {"transport": "wireless", "port": session.port.device, "online": True},
            masterName=match.group(1), legacy=True,
        )
        return

    timestamp = datetime.now().strftime("%H:%M:%S")
    reply = re.match(r"(\S+)>\s+(.*)", text)
    body = reply.group(2) if reply else text
    target = reply.group(1) if reply else (
        info.device_id if info and info.role == "robot" else None
    )
    _emit_calibration_values(body, target)
    if body.startswith("SEQ_"):
        process_serial_line(body)
    elif not any(marker in text for marker in ("MIRA_DEVICE", "MIRA_EVENT", "MIRA_DISCOVER")):
        socketio.emit("console_line", {
            "text": text, "type": "response" if reply else "info", "time": timestamp,
        })


def _route_command(target, command):
    """Send a command exactly once to each selected MAC."""
    if not device_manager and not ble_manager:
        return False
    if target in (None, "all"):
        selected = [robot for robot in robots.values() if robot.get("endpoints")]
    else:
        target_upper = str(target).upper()
        selected = [
            robot for robot in robots.values()
            if robot["mac"] == target_upper or robot.get("masterName") == target or robot.get("name") == target
        ]

    # Preserve synchronized broadcast for the simple, unambiguous topology.
    all_endpoints = [e for robot in selected for e in robot.get("endpoints", {}).values()]
    wireless_ports = {e["port"] for e in all_endpoints if e["transport"] == "wireless"}
    if target in (None, "all") and selected and len(wireless_ports) == 1 and all(
        len(robot["endpoints"]) == 1 and next(iter(robot["endpoints"].values()))["transport"] == "wireless"
        for robot in selected
    ):
        return device_manager.write(next(iter(wireless_ports)), command)

    sent = False
    for robot in selected:
        endpoints = list(robot.get("endpoints", {}).values())
        direct = next((e for e in endpoints if e["transport"] == "usb"), None)
        bluetooth = next((e for e in endpoints if e["transport"] == "ble"), None)
        endpoint = direct or bluetooth or next((e for e in endpoints if e["transport"] == "wireless"), None)
        if endpoint:
            if endpoint["transport"] == "ble":
                sent = bool(ble_manager and ble_manager.write(endpoint["port"], command)) or sent
            else:
                outgoing = command if endpoint["transport"] == "usb" else f"@{robot['mac']} {command}"
                sent = device_manager.write(endpoint["port"], outgoing) or sent
    return sent


def _update_state_changed():
    if firmware_updater:
        socketio.emit("update_status", firmware_updater.state)


device_manager = DeviceManager(
    _managed_line,
    _device_state_changed,
    inspector=BoardInspector(firmware_catalog.identify_fingerprint),
)
firmware_updater = FirmwareUpdater(device_manager, firmware_catalog, _update_state_changed)
ble_manager = BleManager(_managed_line, _device_state_changed)

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

    if device_manager:
        device_manager.stop()

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
    return send_from_directory(str(STATIC_DIR), "index.html")

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

    if any(ord(character) < 0x20 or ord(character) > 0x7e for character in new_name):
        return jsonify({"error": "Name must use printable ASCII characters"}), 400

    # Find current master-side name for this robot
    robot = robots.get(mac)
    if not robot:
        return jsonify({"error": "Robot not found"}), 404

    if not _route_command(mac, f"name set {new_name}"):
        return jsonify({"error": "Robot is not connected"}), 409

    # Update local state
    robot["name"] = new_name
    name_map[mac] = new_name
    save_names(name_map)
    name_migrations.add(mac)

    socketio.emit("robot_list", get_robot_list())
    return jsonify({"ok": True})

@app.route("/api/serial/ports")
def api_serial_ports():
    return jsonify({
        "ports": list_serial_ports(),
        "current": None,
        "connected": bool(device_manager and device_manager.connected_sessions()),
        "devices": device_manager.snapshot() if device_manager else [],
    })

@app.route("/api/serial/connect", methods=["POST"])
def api_serial_connect():
    # Retained for API compatibility. Discovery is automatic.
    if device_manager:
        device_manager.scan_once()
    return jsonify({"ok": True, "automatic": True})

@app.route("/api/serial/disconnect", methods=["POST"])
def api_serial_disconnect():
    return jsonify({"error": "Mira manages device connections automatically."}), 409


@app.route("/api/devices")
def api_devices():
    return jsonify({
        "devices": _device_snapshot(),
        "robots": get_robot_list(),
    })


@app.route("/api/ble/connect", methods=["POST"])
def api_ble_connect():
    data = request.json or {}
    try:
        ble_manager.connect(data.get("address", ""))
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify({"ok": True})


@app.route("/api/ble/disconnect", methods=["POST"])
def api_ble_disconnect():
    data = request.json or {}
    ble_manager.disconnect(data.get("address", ""))
    return jsonify({"ok": True})


@app.route("/api/updates", methods=["GET"])
def api_updates():
    force = request.args.get("refresh") == "1"
    manifest = firmware_catalog.refresh(force=force)
    devices_by_id = {}
    if device_manager:
        for session in device_manager.firmware_sessions():
            info = session.info
            entry = firmware_catalog.entry(info.role)
            devices_by_id[info.device_id] = {
                "deviceId": info.device_id,
                "role": info.role,
                "firmware": info.firmware,
                "legacy": info.legacy,
                "latest": entry.get("version") if entry else None,
                "canUpdate": True,
                "repairRequired": session.state == "repair",
                "updateAvailable": session.state == "repair" or firmware_catalog.update_available(
                    info.role, info.firmware, info.legacy
                ),
            }
    # Report wireless-only robots too, so the UI can advise connecting them by
    # USB when their controller reports old or unknown firmware.
    for robot in robots.values():
        if robot["mac"] in devices_by_id:
            continue
        entry = firmware_catalog.entry("robot")
        current = robot.get("firmware")
        if current == "unknown":
            current = None
        devices_by_id[robot["mac"]] = {
            "deviceId": robot["mac"], "role": "robot", "firmware": current,
            "legacy": robot.get("legacy", not current),
            "latest": entry.get("version") if entry else None,
            "canUpdate": False,
            "updateAvailable": firmware_catalog.update_available(
                "robot", current, robot.get("legacy", not current)
            ),
        }
    return jsonify({
        "devices": list(devices_by_id.values()), "available": bool(manifest),
        "error": firmware_catalog.error, "update": firmware_updater.state,
    })


@app.route("/api/updates/start", methods=["POST"])
def api_update_start():
    data = request.json or {}
    try:
        firmware_updater.start(data.get("deviceId", ""), data.get("role", ""), data.get("port"))
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify({"ok": True})


@app.route("/api/updates/status", methods=["GET"])
def api_update_status():
    return jsonify(firmware_updater.state)


@app.route("/api/devices/erase", methods=["POST"])
def api_device_erase():
    data = request.json or {}
    try:
        firmware_updater.erase(data.get("deviceId", ""))
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify({"ok": True})

@app.route("/api/sequence/autosave", methods=["POST"])
def api_sequence_autosave():
    data = request.json
    with AUTOSAVE_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    return jsonify({"ok": True})

@app.route("/api/sequence/autoload", methods=["GET"])
def api_sequence_autoload():
    candidates = [AUTOSAVE_FILE]
    if LEGACY_AUTOSAVE_FILE != AUTOSAVE_FILE:
        candidates.append(LEGACY_AUTOSAVE_FILE)
    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
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
    devices = _device_snapshot()
    emit("serial_status", {"connected": bool([d for d in devices if d["state"] == "connected"])})
    emit("device_inventory", {"devices": devices})
    emit("robot_list", get_robot_list())

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

    if not _route_command(target, command) and device_type == "robot":
        # Compatibility path for the legacy single-port runtime and tests.
        serial_write(command)

@socketio.on("request_robot_list")
def ws_request_robot_list():
    """Client requests a fresh robot list from the master."""
    if device_manager:
        for session in device_manager.connected_sessions():
            if session.info.role == "wireless_controller":
                session.write("swarm list")

# ---------------------------------------------------------------------------
# Application startup
# ---------------------------------------------------------------------------

def initialize_serial():
    """Start continuous automatic USB and Bluetooth discovery."""
    threading.Thread(
        target=firmware_catalog.refresh,
        kwargs={"force": True},
        name="mira-firmware-catalog",
        daemon=True,
    ).start()
    device_manager.start()
    ble_manager.start()
    print("  Automatic USB and Bluetooth robot discovery started")
    return None


def shutdown_connections():
    """Stop every hardware transport before the desktop window exits."""
    if ble_manager:
        ble_manager.stop()
    disconnect_serial()


def run_server(host="127.0.0.1", port=5050):
    """Run Mira's local UI server."""
    socketio.run(
        app,
        host=host,
        port=port,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    print()
    print("═══════════════════════════════════════════")
    print("  Mira Swarm Controller — Web Server")
    print("═══════════════════════════════════════════")
    print()

    instance_lock = InstanceLock()
    if not instance_lock.acquire():
        print("  Mira is already running. Use the existing Mira window at http://localhost:5050/")
        raise SystemExit(0)

    initialize_serial()

    print()
    print("  Open http://localhost:5050 in your browser")
    print()

    run_server(
        host=os.environ.get("MIRA_HOST", "127.0.0.1"),
        port=int(os.environ.get("MIRA_PORT", "5050")),
    )
