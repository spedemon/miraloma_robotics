"""Read-only ESP32-C3 flash inspection used when a board cannot identify itself."""

from __future__ import annotations

import binascii
import hashlib
import logging
import re
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PARTITION_TABLE_OFFSET = 0x8000
PARTITION_TABLE_SIZE = 0x1000
DEFAULT_APP_OFFSET = 0x10000
APP_DESCRIPTION_SIZE = 0x120
ESP_IMAGE_MAGIC = 0xE9
ESP32C3_CHIP_ID = 5
APP_DESCRIPTION_MAGIC = 0xABCD5432


@dataclass(frozen=True)
class Partition:
    type: int
    subtype: int
    offset: int
    size: int
    label: str


@dataclass(frozen=True)
class BoardInspection:
    kind: str
    mac: str | None = None
    role: str | None = None
    firmware: str | None = None
    fingerprint: str | None = None
    detail: str | None = None


def parse_partition_table(data: bytes) -> list[Partition] | None:
    """Parse and validate an ESP-IDF partition table, including its MD5 entry."""
    entries: list[Partition] = []
    table_bytes = bytearray()
    for offset in range(0, min(len(data), PARTITION_TABLE_SIZE), 32):
        entry = data[offset:offset + 32]
        if len(entry) < 32 or entry == b"\xff" * 32:
            break
        magic = struct.unpack_from("<H", entry)[0]
        if magic == 0xEBEB:
            if entry[16:32] != hashlib.md5(table_bytes).digest():
                return None
            break
        if magic != 0x50AA:
            return None
        _magic, part_type, subtype, part_offset, size, raw_label, _flags = struct.unpack(
            "<HBBII16sI", entry
        )
        label = raw_label.split(b"\0", 1)[0].decode("ascii", errors="replace")
        entries.append(Partition(part_type, subtype, part_offset, size, label))
        table_bytes.extend(entry)
    if not entries:
        return None
    # Modern ESP-IDF tables include a checksum. Accept a valid legacy table,
    # but never accept a present checksum that did not verify above.
    return entries


def parse_app_fingerprint(data: bytes) -> str | None:
    """Return the ELF fingerprint from a valid ESP32-C3 application header."""
    if len(data) < 0xD0 or data[0] != ESP_IMAGE_MAGIC:
        return None
    chip_id = struct.unpack_from("<H", data, 12)[0]
    app_magic = struct.unpack_from("<I", data, 0x20)[0]
    if chip_id != ESP32C3_CHIP_ID or app_magic != APP_DESCRIPTION_MAGIC:
        return None
    return data[0xB0:0xD0].hex()


def selected_app_partition(partitions: list[Partition], flash: bytes) -> Partition | None:
    """Select the same factory/OTA application the ESP-IDF bootloader selects."""
    factory = next((part for part in partitions if part.type == 0 and part.subtype == 0), None)
    ota_apps = sorted(
        (part for part in partitions if part.type == 0 and 0x10 <= part.subtype <= 0x1F),
        key=lambda part: part.subtype,
    )
    ota_data = next((part for part in partitions if part.type == 1 and part.subtype == 0), None)
    if not ota_apps:
        return factory or next((part for part in partitions if part.type == 0), None)
    if not ota_data:
        return factory or ota_apps[0]

    relative = ota_data.offset - PARTITION_TABLE_OFFSET
    candidates: list[tuple[int, int]] = []
    for copy_index in range(2):
        entry_offset = relative + copy_index * 0x1000
        entry = flash[entry_offset:entry_offset + 32]
        if len(entry) < 32:
            continue
        sequence, _label, state, checksum = struct.unpack("<I20sII", entry)
        expected = binascii.crc32(struct.pack("<I", sequence), 0xFFFFFFFF) & 0xFFFFFFFF
        if sequence != 0xFFFFFFFF and state not in {3, 4} and checksum == expected:
            candidates.append((sequence, copy_index))
    if not candidates:
        return factory or ota_apps[0]
    sequence = max(candidates)[0]
    return ota_apps[(sequence - 1) % len(ota_apps)]


class BoardInspector:
    """Classify a silent ESP32-C3 without changing its flash."""

    def __init__(self, identify_fingerprint: Callable[[str], dict | None]):
        self.identify_fingerprint = identify_fingerprint

    def inspect(self, port_resolver: Callable[[], str]) -> BoardInspection:
        with tempfile.TemporaryDirectory(prefix="mira-inspect-") as temp_dir:
            initial_path = Path(temp_dir) / "initial.bin"
            try:
                # This range includes the partition table, normal OTA metadata,
                # and the standard app0 description at 0x10000.
                output = self._read_flash(
                    port_resolver,
                    PARTITION_TABLE_OFFSET,
                    DEFAULT_APP_OFFSET + APP_DESCRIPTION_SIZE - PARTITION_TABLE_OFFSET,
                    initial_path,
                )
            except RuntimeError as exc:
                return BoardInspection("unknown", detail=str(exc))

            flash = initial_path.read_bytes()
            mac = self._parse_mac(output)
            if flash and all(value == 0xFF for value in flash):
                return BoardInspection("erased", mac=mac)

            partitions = parse_partition_table(flash[:PARTITION_TABLE_SIZE])
            selected = selected_app_partition(partitions, flash) if partitions else None
            app_offset = selected.offset if selected else DEFAULT_APP_OFFSET
            relative = app_offset - PARTITION_TABLE_OFFSET
            app_data = flash[relative:relative + APP_DESCRIPTION_SIZE]
            if len(app_data) < APP_DESCRIPTION_SIZE:
                app_path = Path(temp_dir) / "app.bin"
                try:
                    output += self._read_flash(
                        port_resolver, app_offset, APP_DESCRIPTION_SIZE, app_path
                    )
                    app_data = app_path.read_bytes()
                    mac = mac or self._parse_mac(output)
                except RuntimeError as exc:
                    return BoardInspection("unknown", mac=mac, detail=str(exc))

            fingerprint = parse_app_fingerprint(app_data)
            if fingerprint:
                known = self.identify_fingerprint(fingerprint)
                if known:
                    return BoardInspection(
                        "mira",
                        mac=mac,
                        role=known["role"],
                        firmware=known["version"],
                        fingerprint=fingerprint,
                    )
                return BoardInspection("other_firmware", mac=mac, fingerprint=fingerprint)
            if partitions:
                return BoardInspection("corrupt", mac=mac)
            return BoardInspection("erased" if not flash.strip(b"\xff") else "corrupt", mac=mac)

    @staticmethod
    def _parse_mac(output: str) -> str | None:
        match = re.search(r"\bMAC:\s*([0-9a-f:]{17})", output, re.IGNORECASE)
        return match.group(1).upper() if match else None

    @staticmethod
    def _read_flash(
        port_resolver: Callable[[], str], address: int, size: int, destination: Path
    ) -> str:
        last_output = ""
        for baud in ("460800", "115200"):
            time.sleep(0.35)
            port = port_resolver()
            if getattr(sys, "frozen", False):
                try:
                    from esptool import cmds

                    esp = cmds.detect_chip(
                        port=port,
                        baud=115200,
                        connect_mode="default-reset",
                        connect_attempts=7,
                    )
                    try:
                        if esp.CHIP_NAME != "ESP32-C3":
                            raise RuntimeError(f"Unsupported chip: {esp.CHIP_NAME}")
                        mac_bytes = esp.read_mac("BASE_MAC")
                        esp = cmds.run_stub(esp)
                        cmds.attach_flash(esp)
                        data = cmds.read_flash(
                            esp, address, size, output=None, no_progress=True
                        )
                        if data is None:
                            raise RuntimeError("The board returned no flash data.")
                        destination.write_bytes(data)
                        mac = ":".join(f"{value:02X}" for value in mac_bytes)
                        return f"MAC: {mac}"
                    finally:
                        try:
                            esp.hard_reset()
                        finally:
                            esp._port.close()
                except Exception as exc:
                    last_output = str(exc)
                    logging.warning(
                        "Read-only board inspection failed on %s: %s", port, last_output
                    )
                    continue
            args = [
                "--chip", "esp32c3", "--port", port, "--baud", baud,
                "--before", "default-reset", "--after", "hard-reset",
                "read-flash", hex(address), hex(size), str(destination),
            ]
            try:
                process = subprocess.run(
                    [sys.executable, "-m", "esptool", *args],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=25,
                )
                last_output = process.stdout or ""
                if process.returncode == 0 and destination.exists():
                    return last_output
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                last_output = str(exc)
            logging.warning("Read-only board inspection failed on %s: %s", port, last_output[-500:])
        normalized = re.sub(r"\s+", " ", last_output).lower()
        if any(marker in normalized for marker in (
            "resource busy", "device or resource busy", "could not open",
            "failed to open", "access is denied", "permission denied",
        )):
            raise RuntimeError(
                "Another program is using this USB board. Close any other Mira "
                "window or serial monitor, reconnect the board, and try again."
            )
        if "failed to connect" in normalized or "no serial data" in normalized:
            raise RuntimeError(
                "Mira could not inspect this board. Reconnect it; if needed, hold BOOT, "
                "tap RESET, and release BOOT."
            )
        raise RuntimeError("Mira could not inspect this USB board. Reconnect it and try again.")
