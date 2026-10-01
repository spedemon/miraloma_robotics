"""Cross-platform Bluetooth Low Energy discovery and Mira sessions."""

from __future__ import annotations

import asyncio
import re
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # Source/web-only installations may intentionally omit BLE.
    BleakClient = None
    BleakScanner = None


SERVICE_UUID = "7f510001-1b15-4f8e-9f5d-6f6d69726100"
COMMAND_UUID = "7f510002-1b15-4f8e-9f5d-6f6d69726100"
RESPONSE_UUID = "7f510003-1b15-4f8e-9f5d-6f6d69726100"
DEVICE_INFO_UUID = "7f510004-1b15-4f8e-9f5d-6f6d69726100"


@dataclass
class BleDeviceInfo:
    role: str
    device_id: str
    firmware: str | None = None
    protocol: int = 0
    hardware: str | None = None
    legacy: bool = False


def parse_device_info(text: str) -> BleDeviceInfo:
    values = dict(re.findall(r"([a-z_]+)=([^\s]+)", text))
    if values.get("role") != "robot" or not values.get("id"):
        raise ValueError("Bluetooth device did not provide valid Mira identity metadata")
    try:
        protocol = int(values.get("protocol", "0"))
    except ValueError:
        protocol = 0
    return BleDeviceInfo(
        role="robot",
        device_id=values["id"].upper(),
        firmware=values.get("firmware"),
        protocol=protocol,
        hardware=values.get("hardware"),
        legacy=protocol < 2,
    )


@dataclass
class BleSession:
    address: str
    name: str
    client: object
    info: BleDeviceInfo
    state: str = "connected"
    rx_buffer: str = ""
    last_seen: float = field(default_factory=time.monotonic)

    @property
    def port(self):
        # Device-manager consumers use only port.device.
        return SimpleNamespace(device=f"ble:{self.address}")


class BleManager:
    """Runs Bleak on a dedicated asyncio thread and exposes sync operations."""

    def __init__(
        self,
        on_line: Callable[[BleSession, str], None],
        on_change: Callable[[], None],
        *,
        scanner_factory=None,
        client_factory=None,
    ):
        self.on_line = on_line
        self.on_change = on_change
        self.scanner_factory = scanner_factory or BleakScanner
        self.client_factory = client_factory or BleakClient
        self.discovered: dict[str, dict] = {}
        self.sessions: dict[str, BleSession] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return self.scanner_factory is not None and self.client_factory is not None

    def start(self) -> None:
        if not self.available or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mira-ble", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._disconnect_all(), self._loop)
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread:
            self._thread.join(timeout=4)

    def connect(self, address: str) -> None:
        if not self._loop:
            raise RuntimeError("Bluetooth discovery has not started yet.")
        with self._lock:
            if address not in self.discovered:
                raise RuntimeError("That Bluetooth robot is no longer nearby.")
            self.discovered[address]["state"] = "connecting"
        self.on_change()
        asyncio.run_coroutine_threadsafe(self._connect(address), self._loop)

    def disconnect(self, address: str) -> None:
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._disconnect(address), self._loop)

    def write(self, address_or_port: str, command: str) -> bool:
        address = address_or_port.removeprefix("ble:")
        with self._lock:
            session = self.sessions.get(address)
        if not session or not self._loop:
            return False
        future = asyncio.run_coroutine_threadsafe(
            session.client.write_gatt_char(COMMAND_UUID, command.encode("utf-8"), response=True),
            self._loop,
        )
        future.add_done_callback(lambda completed: self._write_finished(address, completed))
        return True

    def connected_sessions(self) -> list[BleSession]:
        with self._lock:
            return list(self.sessions.values())

    def snapshot(self) -> list[dict]:
        with self._lock:
            devices = [dict(item) for item in self.discovered.values()]
            sessions = dict(self.sessions)
        result = []
        for item in devices:
            session = sessions.get(item["address"])
            info = session.info if session else None
            result.append({
                "port": f"ble:{item['address']}",
                "address": item["address"],
                "name": item.get("name") or "Mira robot",
                "state": "connected" if session else item.get("state", "available"),
                "role": "robot",
                "deviceId": info.device_id if info else None,
                "firmware": info.firmware if info else None,
                "protocol": info.protocol if info else None,
                "legacy": info.legacy if info else False,
                "transport": "ble",
                "rssi": item.get("rssi"),
            })
        return result

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._scan_loop())
        finally:
            self._loop.run_until_complete(self._disconnect_all())
            self._loop.close()
            self._loop = None

    async def _scan_loop(self) -> None:
        while not self._stop.is_set():
            try:
                found = await self.scanner_factory.discover(
                    timeout=3.0,
                    return_adv=True,
                    service_uuids=[SERVICE_UUID],
                )
                now = time.monotonic()
                with self._lock:
                    for address, pair in found.items():
                        device, advertisement = pair
                        services = {value.lower() for value in advertisement.service_uuids or []}
                        if SERVICE_UUID not in services and not (device.name or "").startswith("Mira-"):
                            continue
                        previous = self.discovered.get(address, {})
                        self.discovered[address] = {
                            "address": address,
                            "name": device.name or advertisement.local_name or previous.get("name") or "Mira robot",
                            "rssi": advertisement.rssi,
                            "last_seen": now,
                            "state": previous.get("state", "available"),
                        }
                    stale = [
                        address for address, item in self.discovered.items()
                        if address not in self.sessions and now - item.get("last_seen", 0) > 12
                    ]
                    for address in stale:
                        self.discovered.pop(address, None)
                self.on_change()
            except Exception:
                # Bluetooth can be temporarily disabled or unavailable after sleep.
                pass
            await asyncio.sleep(1)

    async def _connect(self, address: str) -> None:
        with self._lock:
            item = self.discovered.get(address)
        if not item:
            return
        client = self.client_factory(address, disconnected_callback=lambda _: self._did_disconnect(address))
        try:
            await client.connect()
            metadata = bytes(await client.read_gatt_char(DEVICE_INFO_UUID)).decode("utf-8", errors="replace")
            info = parse_device_info(metadata)
            session = BleSession(address, item["name"], client, info)
            with self._lock:
                self.sessions[address] = session
                self.discovered[address]["state"] = "connected"
            await client.start_notify(RESPONSE_UUID, lambda _, data: self._notification(address, data))
            self.on_change()
            self.on_line(session, f"MIRA_DEVICE ble role=robot id={info.device_id} firmware={info.firmware or 'unknown'} protocol={info.protocol} hardware={info.hardware or 'esp32c3'}")
        except Exception:
            try:
                await client.disconnect()
            except Exception:
                pass
            with self._lock:
                if address in self.discovered:
                    self.discovered[address]["state"] = "available"
            self.on_change()

    async def _disconnect(self, address: str) -> None:
        with self._lock:
            session = self.sessions.get(address)
        if session:
            try:
                await session.client.disconnect()
            finally:
                self._did_disconnect(address)

    async def _disconnect_all(self) -> None:
        with self._lock:
            addresses = list(self.sessions)
        for address in addresses:
            await self._disconnect(address)

    def _did_disconnect(self, address: str) -> None:
        with self._lock:
            self.sessions.pop(address, None)
            if address in self.discovered:
                self.discovered[address]["state"] = "available"
        self.on_change()

    def _notification(self, address: str, data: bytearray) -> None:
        with self._lock:
            session = self.sessions.get(address)
            if not session:
                return
            session.rx_buffer += bytes(data).decode("utf-8", errors="replace")
            lines = session.rx_buffer.split("\n")
            session.rx_buffer = lines.pop()
        for line in lines:
            line = line.rstrip("\r")
            if line:
                self.on_line(session, line)

    def _write_finished(self, address: str, future) -> None:
        try:
            future.result()
        except Exception:
            self._did_disconnect(address)
