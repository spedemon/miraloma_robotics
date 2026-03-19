"""
robot_hal.py — Hardware Abstraction Layer

Thread-safe pyserial wrapper that converts Python method calls
into UART command strings for the Micro:bit peripheral bridge.
"""

import threading
import time
from typing import Optional

import serial
import serial.tools.list_ports


class RobotHAL:
    """Thread-safe interface to the Micro:bit mecanum robot via UART."""

    def __init__(self) -> None:
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._connected = False

    # ── Connection ────────────────────────────────────────────────

    @staticmethod
    def list_ports() -> list[str]:
        """Return a list of available serial port names."""
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port: str, baud: int = 115200, timeout: float = 1.0) -> None:
        """Open a serial connection to the Micro:bit."""
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

    def _send(self, message: str) -> None:
        """Send a raw UART string (thread-safe). Appends newline."""
        with self._lock:
            if not self.is_connected:
                raise ConnectionError("Robot is not connected")
            self._serial.write(f"{message}\n".encode("ascii"))
            self._serial.flush()

    def _query(self, message: str, wait: float = 0.1) -> str:
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

    # ── Motor Control ─────────────────────────────────────────────

    def drive(self, l1: int, l2: int, r1: int, r2: int) -> None:
        """Drive the 4 mecanum motors.

        Args:
            l1: Left-front motor speed  (-255 to 255)
            l2: Left-rear motor speed   (-255 to 255)
            r1: Right-front motor speed (-255 to 255)
            r2: Right-rear motor speed  (-255 to 255)
        """
        l1, l2, r1, r2 = (max(-255, min(255, v)) for v in (l1, l2, r1, r2))
        self._send(f"M:{l1}:{l2}:{r1}:{r2}")

    def stop(self) -> None:
        """Emergency all-stop — highest priority."""
        self._send("M:0:0:0:0")

    # ── Servo ─────────────────────────────────────────────────────

    def set_servo(self, angle: int) -> None:
        """Set the ultrasonic servo to *angle* degrees (0–180)."""
        angle = max(0, min(180, angle))
        self._send(f"S:{angle}")

    # ── Sensors ───────────────────────────────────────────────────

    def read_distance(self) -> float:
        """Read ultrasonic distance in cm."""
        resp = self._query("D:?")
        try:
            return float(resp)
        except ValueError:
            return -1.0

    def read_imu(self) -> dict:
        """Read IMU orientation → {pitch, roll, heading} in degrees."""
        resp = self._query("I:?")
        try:
            parts = resp.split(":")
            return {
                "pitch": float(parts[0]),
                "roll": float(parts[1]),
                "heading": float(parts[2]),
            }
        except (ValueError, IndexError):
            return {"pitch": 0.0, "roll": 0.0, "heading": 0.0}

    # ── Display & Audio ──────────────────────────────────────────

    def display_text(self, text: str) -> None:
        """Scroll *text* on the Micro:bit 5×5 LED matrix."""
        safe = text.replace(":", " ").replace("\n", " ")
        self._send(f"L:{safe}")

    def play_tone(self, freq: int) -> None:
        """Play a tone at *freq* Hz through the buzzer."""
        self._send(f"B:{freq}")
