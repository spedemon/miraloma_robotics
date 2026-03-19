"""
robot_hal.py — Hardware Abstraction Layer

Thread-safe pyserial wrapper that converts Python method calls
into UART command strings for the robot peripheral bridge.

Supports multiple robot types via protocol YAML files. Commands
are looked up dynamically from the loaded protocol.
"""

import threading
import time
from typing import Optional
from pathlib import Path

import yaml
import serial
import serial.tools.list_ports


class RobotHAL:
    """Thread-safe interface to the robot via UART.

    Supports any robot whose protocol is defined in a YAML file.
    """

    def __init__(self) -> None:
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._connected = False
        # Protocol data loaded from YAML
        self._protocol: dict = {}
        self._setters: dict[str, dict] = {}
        self._getters: dict[str, dict] = {}
        self._robot_name: str = ""

    # ── Protocol Loading ─────────────────────────────────────────

    def load_protocol(self, yaml_path: str | Path) -> None:
        """Load a robot protocol YAML file.

        Parses setters and getters into quick-lookup dicts keyed by ID.
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Protocol file not found: {path}")

        with open(path) as f:
            self._protocol = yaml.safe_load(f)

        self._robot_name = self._protocol.get("name", "Unknown")
        self._setters = {
            cmd["id"]: cmd for cmd in self._protocol.get("setters", [])
        }
        self._getters = {
            cmd["id"]: cmd for cmd in self._protocol.get("getters", [])
        }

    @property
    def robot_name(self) -> str:
        return self._robot_name

    @property
    def protocol(self) -> dict:
        return self._protocol

    @property
    def setter_ids(self) -> list[str]:
        return list(self._setters.keys())

    @property
    def getter_ids(self) -> list[str]:
        return list(self._getters.keys())

    # ── Connection ────────────────────────────────────────────────

    @staticmethod
    def list_ports() -> list[str]:
        """Return a list of available serial port names."""
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port: str, baud: int = 115200, timeout: float = 1.0) -> None:
        """Open a serial connection to the robot."""
        with self._lock:
            if self._serial and self._serial.is_open:
                self._serial.close()
            self._serial = serial.Serial(port, baud, timeout=timeout)
            self._connected = True

    def disconnect(self) -> None:
        """Close the serial connection."""
        with self._lock:
            if self._serial and self._serial.is_open:
                self._serial.close()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._serial is not None and self._serial.is_open

    # ── Low-level I/O ─────────────────────────────────────────────

    def _send_raw(self, message: str) -> None:
        """Send a raw UART string (thread-safe). Appends newline."""
        with self._lock:
            if not self.is_connected:
                raise ConnectionError("Robot is not connected")
            self._serial.write(f"{message}\n".encode("ascii"))
            self._serial.flush()

    def _query_raw(self, message: str, wait: float = 0.1) -> str:
        """Send a command and read back the response line (thread-safe)."""
        with self._lock:
            if not self.is_connected:
                raise ConnectionError("Robot is not connected")
            self._serial.reset_input_buffer()
            self._serial.write(f"{message}\n".encode("ascii"))
            self._serial.flush()
            time.sleep(wait)
            line = self._serial.readline().decode("ascii", errors="replace").strip()
            return line

    # ── Generic Command Interface ─────────────────────────────────

    def send_command(self, action_id: str, value: int = 0) -> None:
        """Send a setter command by its protocol ID.

        Looks up the UART command template from the loaded protocol,
        substitutes the value, and sends it.

        Args:
            action_id: The command ID (e.g., 'MFW', 'STP', 'ACT')
            value: The value parameter (speed, angle, action_id, etc.)
        """
        cmd_def = self._setters.get(action_id)
        if cmd_def is None:
            raise ValueError(
                f"Unknown setter command '{action_id}' for robot '{self._robot_name}'. "
                f"Available: {list(self._setters.keys())}"
            )
        # Build the UART string from the command template
        # Template format: "S:MFW:<speed>" — replace <...> with actual value
        cmd_str = cmd_def["command"]
        # Replace any <param_name> placeholder with the value
        import re
        cmd_str = re.sub(r"<[^>]+>", str(value), cmd_str)
        self._send_raw(cmd_str)

    def read_sensor(self, sensor_id: str, value: int = 0) -> str:
        """Read a getter (sensor) by its protocol ID.

        Args:
            sensor_id: The getter ID (e.g., 'ULD', 'LTR')
            value: Optional parameter (e.g., which sensor to read)

        Returns:
            The raw response string from the robot.
        """
        cmd_def = self._getters.get(sensor_id)
        if cmd_def is None:
            raise ValueError(
                f"Unknown getter command '{sensor_id}' for robot '{self._robot_name}'. "
                f"Available: {list(self._getters.keys())}"
            )
        cmd_str = cmd_def["command"]
        import re
        cmd_str = re.sub(r"<[^>]+>", str(value), cmd_str)
        return self._query_raw(cmd_str)

    # ── Universal Commands ────────────────────────────────────────

    def stop(self) -> None:
        """Emergency all-stop — highest priority.

        Sends the STP command if loaded from protocol,
        otherwise sends a generic motor-zero command.
        """
        if "STP" in self._setters:
            self.send_command("STP", 0)
        else:
            # Fallback: try generic motor stop
            self._send_raw("S:STP:0")

    # ── Convenience Methods (backwards-compatible) ────────────────

    def drive(self, l1: int, l2: int, r1: int, r2: int) -> None:
        """Drive the 4 mecanum motors (Mecanum-specific).

        Args:
            l1: Left-front motor speed  (-255 to 255)
            l2: Left-rear motor speed   (-255 to 255)
            r1: Right-front motor speed (-255 to 255)
            r2: Right-rear motor speed  (-255 to 255)
        """
        l1, l2, r1, r2 = (max(-255, min(255, v)) for v in (l1, l2, r1, r2))
        self._send_raw(f"M:{l1}:{l2}:{r1}:{r2}")

    def set_servo(self, angle: int) -> None:
        """Set the ultrasonic servo to *angle* degrees (0–180)."""
        self.send_command("ULA", max(0, min(180, angle)))

    def read_distance(self) -> float:
        """Read ultrasonic distance in cm."""
        try:
            resp = self.read_sensor("ULD")
            return float(resp)
        except (ValueError, Exception):
            return -1.0

    def display_text(self, text: str) -> None:
        """Scroll *text* on the Micro:bit 5×5 LED matrix."""
        safe = text.replace(":", " ").replace("\n", " ")
        self._send_raw(f"L:{safe}")

    def play_tone(self, freq: int) -> None:
        """Play a tone at *freq* Hz through the buzzer."""
        self._send_raw(f"B:{freq}")
