"""Automatic discovery and lifecycle management for Mira USB devices."""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import serial
import serial.tools.list_ports


BAUD_RATE = 115200
SCAN_INTERVAL = 0.75
PROBE_TIMEOUT = 2.5
UNRECOGNIZED_DISCONNECT_GRACE = 4.0

# Espressif native USB plus the USB/UART bridges commonly fitted to ESP32-C3
# boards.  Metadata only selects candidates; the Mira handshake is authoritative.
KNOWN_VIDS = {0x303A, 0x10C4, 0x1A86, 0x0403}
KNOWN_TOKENS = (
    "usbmodem", "usbserial", "espressif", "esp32", "cp210", "ch340",
    "ch910", "wchusbserial",
)


@dataclass(frozen=True)
class PortDescriptor:
    device: str
    description: str = ""
    hwid: str = ""
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    location: str | None = None

    @classmethod
    def from_pyserial(cls, port) -> "PortDescriptor":
        return cls(
            device=port.device,
            description=port.description or "",
            hwid=port.hwid or "",
            vid=getattr(port, "vid", None),
            pid=getattr(port, "pid", None),
            serial_number=getattr(port, "serial_number", None),
            location=getattr(port, "location", None),
        )

    @property
    def physical_key(self) -> str:
        return self.serial_number or self.location or self.device


@dataclass
class DeviceInfo:
    role: str
    device_id: str
    firmware: str | None = None
    protocol: int = 0
    hardware: str = "esp32c3"
    legacy: bool = False


@dataclass
class DeviceSession:
    port: PortDescriptor
    handle: object
    nonce: str
    state: str = "probing"
    info: DeviceInfo | None = None
    opened_at: float = field(default_factory=time.monotonic)
    last_rx_at: float = field(default_factory=time.monotonic)
    last_identity_at: float = field(default_factory=time.monotonic)
    last_probe_at: float = 0.0
    stopped: threading.Event = field(default_factory=threading.Event)
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    reader_thread: threading.Thread | None = None

    @property
    def key(self) -> str:
        return self.port.device

    def write(self, text: str) -> bool:
        with self.write_lock:
            if self.stopped.is_set() or not getattr(self.handle, "is_open", False):
                return False
            try:
                self.handle.write((text + "\n").encode("utf-8"))
                self.handle.flush()
                return True
            except (serial.SerialException, OSError):
                return False


def is_candidate(port: PortDescriptor) -> bool:
    haystack = f"{port.device} {port.description} {port.hwid}".lower()
    return port.vid in KNOWN_VIDS or any(token in haystack for token in KNOWN_TOKENS)


def parse_device_info(line: str, nonce: str | None = None) -> DeviceInfo | None:
    match = re.search(r"MIRA_DEVICE\s+(\S+)\s+(.+)$", line)
    if not match or (nonce and match.group(1) != nonce):
        return None
    values = dict(re.findall(r"([a-z_]+)=([^\s]+)", match.group(2)))
    role = values.get("role")
    device_id = values.get("id")
    if role not in {"robot", "wireless_controller"} or not device_id:
        return None
    try:
        protocol = int(values.get("protocol", "0"))
    except ValueError:
        protocol = 0
    return DeviceInfo(
        role=role,
        device_id=device_id.upper(),
        firmware=values.get("firmware"),
        protocol=protocol,
        hardware=values.get("hardware", "esp32c3"),
    )


class DeviceManager:
    """Continuously finds, identifies, reconnects, and removes Mira devices."""

    def __init__(
        self,
        on_line: Callable[[DeviceSession, str], None],
        on_change: Callable[[], None],
        serial_factory=serial.Serial,
        port_lister=serial.tools.list_ports.comports,
    ):
        self.on_line = on_line
        self.on_change = on_change
        self.serial_factory = serial_factory
        self.port_lister = port_lister
        self.sessions: dict[str, DeviceSession] = {}
        self._ignored_until: dict[str, float] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._paused_ports: set[str] = set()
        self._missing_since: dict[str, float] = {}

    def start(self) -> None:
        if self._monitor and self._monitor.is_alive():
            return
        self._stop.clear()
        self._monitor = threading.Thread(target=self._monitor_loop, name="mira-usb", daemon=True)
        self._monitor.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            ports = list(self.sessions)
        for port in ports:
            self._remove(port, "application_closed")
        if self._monitor and self._monitor is not threading.current_thread():
            self._monitor.join(timeout=2)

    def scan_once(self) -> None:
        listed = [p for p in self.port_lister() if getattr(p, "device", None)]
        names = {p.device for p in listed}
        # macOS exposes paired tty/cu nodes for some drivers; cu is the correct
        # outbound endpoint and opening both would create duplicate sessions.
        listed = [
            p for p in listed
            if not (p.device.startswith("/dev/tty.") and p.device.replace("/dev/tty.", "/dev/cu.", 1) in names)
        ]
        descriptors = {p.device: PortDescriptor.from_pyserial(p) for p in listed}
        now = time.monotonic()
        with self._lock:
            existing = set(self.sessions)
            paused = set(self._paused_ports)

        # Native USB ESP32-C3 boards can briefly disappear and return with a
        # different tty name while boot-looping without valid firmware. Keep
        # the provisioning card stable and follow the same USB serial/location.
        for old_port in existing - set(descriptors):
            with self._lock:
                session = self.sessions.get(old_port)
            if not session or session.state != "unrecognized":
                continue
            replacement = next(
                (
                    descriptor for descriptor in descriptors.values()
                    if descriptor.physical_key == session.port.physical_key
                    and descriptor.device not in existing
                ),
                None,
            )
            if replacement:
                with self._lock:
                    self.sessions.pop(old_port, None)
                    session.port = replacement
                    self.sessions[replacement.device] = session
                self._missing_since.pop(old_port, None)
                existing.discard(old_port)
                existing.add(replacement.device)
                self.on_change()

        for missing in existing - set(descriptors):
            with self._lock:
                session = self.sessions.get(missing)
            if session and session.state == "unrecognized":
                first_missing = self._missing_since.setdefault(missing, now)
                if now - first_missing < UNRECOGNIZED_DISCONNECT_GRACE:
                    continue
            self._remove(missing, "unplugged")
            self._missing_since.pop(missing, None)
        for present in descriptors:
            self._missing_since.pop(present, None)
        for device, descriptor in descriptors.items():
            if device in existing or device in paused or not is_candidate(descriptor):
                continue
            if self._ignored_until.get(device, 0) > now:
                continue
            self._open(descriptor)
        self._health_check()

    def session_for_device(self, device_id: str) -> DeviceSession | None:
        with self._lock:
            return next(
                (s for s in self.sessions.values() if s.info and s.info.device_id == device_id),
                None,
            )

    def session_for_port(self, port: str) -> DeviceSession | None:
        with self._lock:
            return self.sessions.get(port)

    def session_for_physical_key(self, physical_key: str) -> DeviceSession | None:
        with self._lock:
            return next(
                (session for session in self.sessions.values() if session.port.physical_key == physical_key),
                None,
            )

    def connected_sessions(self) -> list[DeviceSession]:
        with self._lock:
            return [s for s in self.sessions.values() if s.state == "connected" and s.info]

    def write(self, port: str, text: str) -> bool:
        with self._lock:
            session = self.sessions.get(port)
        if not session or not session.write(text):
            if session:
                self._remove(port, "write_failed")
            return False
        return True

    def pause_for_update(self, port: str) -> PortDescriptor | None:
        with self._lock:
            session = self.sessions.get(port)
            descriptor = session.port if session else None
            self._paused_ports.add(port)
        if session:
            session.state = "updating"
            self.on_change()
            self._remove(port, "updating", notify=False)
        return descriptor

    def resume_after_update(self, port: str) -> None:
        with self._lock:
            self._paused_ports.discard(port)
            self._ignored_until.pop(port, None)
        self.on_change()

    def snapshot(self) -> list[dict]:
        with self._lock:
            sessions = list(self.sessions.values())
        return [
            {
                "port": s.port.device,
                "state": s.state,
                "role": s.info.role if s.info else None,
                "deviceId": s.info.device_id if s.info else None,
                "firmware": s.info.firmware if s.info else None,
                "protocol": s.info.protocol if s.info else None,
                "legacy": s.info.legacy if s.info else False,
            }
            for s in sessions
        ]

    def _monitor_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:
                # Enumeration failures are transient on sleep/wake and driver reload.
                pass
            self._stop.wait(SCAN_INTERVAL)

    def _open(self, descriptor: PortDescriptor) -> None:
        try:
            handle = self.serial_factory(descriptor.device, BAUD_RATE, timeout=0.15)
        except (serial.SerialException, OSError):
            self._ignored_until[descriptor.device] = time.monotonic() + 2
            return
        nonce = f"{random.getrandbits(32):08x}"
        session = DeviceSession(descriptor, handle, nonce)
        with self._lock:
            if descriptor.device in self.sessions or descriptor.device in self._paused_ports:
                handle.close()
                return
            self.sessions[descriptor.device] = session
        session.reader_thread = threading.Thread(
            target=self._reader_loop,
            args=(session,),
            name=f"mira-reader-{descriptor.device}",
            daemon=True,
        )
        session.reader_thread.start()
        session.last_probe_at = time.monotonic()
        session.write(f"MIRA_DISCOVER {nonce}")
        threading.Thread(target=self._legacy_probe, args=(session,), daemon=True).start()
        self.on_change()

    def _legacy_probe(self, session: DeviceSession) -> None:
        if session.stopped.wait(0.65):
            return
        if not session.info or session.info.device_id == "pending":
            session.write(f"MIRA_DISCOVER {session.nonce}")
        if session.stopped.wait(0.5):
            return
        if not session.info or session.info.device_id == "pending":
            session.write("id")
        if session.stopped.wait(PROBE_TIMEOUT - 1.15):
            return
        if not session.info or session.info.device_id == "pending":
            # Keep a closed placeholder while the USB device remains present so
            # a blank ESP32-C3 can be intentionally provisioned from the UI.
            session.state = "unrecognized"
            session.stopped.set()
            try:
                session.handle.close()
            except Exception:
                pass
            self.on_change()

    def _reader_loop(self, session: DeviceSession) -> None:
        reason = "reader_stopped"
        try:
            while not self._stop.is_set() and not session.stopped.is_set():
                line = session.handle.readline()
                if not line:
                    continue
                session.last_rx_at = time.monotonic()
                text = line.decode("utf-8", errors="replace").strip("\r\n")
                if not text:
                    continue
                self._identify(session, text)
                self.on_line(session, text)
        except (serial.SerialException, OSError, PermissionError):
            reason = "read_failed"
        except Exception:
            reason = "reader_error"
        finally:
            if not session.stopped.is_set():
                self._remove(session.port.device, reason)

    def _identify(self, session: DeviceSession, text: str) -> None:
        if "invalid header:" in text.lower():
            # A blank/corrupt ESP32-C3 can reset and re-enumerate faster than
            # the normal probe timeout. Surface it immediately for intentional
            # robot/controller provisioning instead of reconnecting forever.
            session.state = "unrecognized"
            session.stopped.set()
            try:
                session.handle.close()
            except Exception:
                pass
            self.on_change()
            return
        info = parse_device_info(text, session.nonce)
        if info:
            session.info = info
            session.last_identity_at = time.monotonic()
        elif "Mira Motor MCU" in text:
            version = self._banner_version(text)
            session.info = DeviceInfo("robot", "pending", version, 0, legacy=True)
        elif "Mira Master MCU" in text:
            version = self._banner_version(text)
            session.info = DeviceInfo("wireless_controller", "pending", version, 0, legacy=True)
        else:
            match = re.search(r"(?:^|\s)ID:\s*([0-9A-Fa-f:]{17})", text)
            if match:
                if session.info and session.info.role == "robot":
                    session.info.device_id = match.group(1).upper()
                else:
                    session.info = DeviceInfo(
                        "robot", match.group(1).upper(), None, 0, legacy=True
                    )
        if session.info and session.info.device_id != "pending" and session.state != "connected":
            session.state = "connected"
            self.on_change()

    @staticmethod
    def _banner_version(text: str) -> str | None:
        match = re.search(r"\bv(\d+\.\d+\.\d+)", text)
        return match.group(1) if match else None

    def _health_check(self) -> None:
        now = time.monotonic()
        with self._lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            if session.state != "connected" or not session.info or session.info.legacy:
                continue
            if now - session.last_identity_at > 9:
                self._remove(session.port.device, "health_timeout")
            elif now - session.last_identity_at > 3 and now - session.last_probe_at > 3:
                session.last_probe_at = now
                if not session.write(f"MIRA_DISCOVER {session.nonce}"):
                    self._remove(session.port.device, "health_write_failed")

    def _remove(self, port: str, reason: str, notify: bool = True) -> None:
        with self._lock:
            session = self.sessions.pop(port, None)
        if not session:
            return
        self._missing_since.pop(port, None)
        session.stopped.set()
        session.state = "lost"
        try:
            session.handle.close()
        except Exception:
            pass
        if session.reader_thread and session.reader_thread is not threading.current_thread():
            session.reader_thread.join(timeout=0.5)
        if notify:
            self.on_change()
