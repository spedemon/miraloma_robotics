"""Firmware catalog, download validation, and ESP32-C3 flashing for Mira."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from app_paths import resource_path, user_data_dir


RELEASE_API = "https://api.github.com/repos/spedemon/miraloma_robotics/releases/latest"


def version_tuple(value: str | None) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value or "")
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


class FirmwareCatalog:
    def __init__(self):
        self.cache_dir = user_data_dir() / "firmware"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest: dict = {}
        self.error: str | None = None
        self.checked_at = 0.0

    def refresh(self, force: bool = False) -> dict:
        if not force and self.manifest and time.time() - self.checked_at < 86400:
            return self.manifest
        self.error = None
        try:
            request = urllib.request.Request(
                RELEASE_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Mira-Desktop"},
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                release = json.load(response)
            asset = next(a for a in release.get("assets", []) if a["name"] == "mira-firmware-manifest.json")
            manifest = self._download_json(asset["browser_download_url"])
            manifest["_assets"] = {a["name"]: a for a in release.get("assets", [])}
            self.manifest = manifest
            (self.cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception as exc:
            self.error = str(exc)
            self.manifest = self._load_fallback()
        self.checked_at = time.time()
        return self.manifest

    def entry(self, role: str) -> dict | None:
        return self.manifest.get(role)

    def update_available(self, role: str, current: str | None, legacy: bool = False) -> bool:
        entry = self.entry(role)
        return bool(entry and (legacy or version_tuple(entry.get("version")) > version_tuple(current)))

    def obtain(self, role: str, provisioning: bool = False) -> tuple[dict, Path]:
        entry = self.entry(role)
        if not entry:
            raise RuntimeError("No firmware is published for this device yet.")
        asset_key = "provisioning_asset" if provisioning else "asset"
        checksum_key = "provisioning_sha256" if provisioning else "sha256"
        filename = entry.get(asset_key)
        checksum = entry.get(checksum_key)
        if not filename or not checksum:
            raise RuntimeError("The firmware package cannot set up a blank board.")
        destination = self.cache_dir / filename
        asset = self.manifest.get("_assets", {}).get(filename)
        if asset and asset.get("digest", "").startswith("sha256:"):
            release_digest = asset["digest"].split(":", 1)[1]
            if release_digest != checksum:
                raise RuntimeError("The published firmware checksums do not agree.")
        if not destination.exists() or self._sha256(destination) != checksum:
            bundled = resource_path("firmware", filename)
            if bundled.exists() and self._sha256(bundled) == checksum:
                destination.write_bytes(bundled.read_bytes())
            else:
                if not asset:
                    raise RuntimeError("The firmware download is missing from this release.")
                self._download_file(asset["browser_download_url"], destination)
        if self._sha256(destination) != checksum:
            destination.unlink(missing_ok=True)
            raise RuntimeError("The firmware download did not pass its safety check.")
        return entry, destination

    def _load_fallback(self) -> dict:
        candidates = [resource_path("firmware", "manifest.json"), self.cache_dir / "manifest.json"]
        for path in candidates:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        return {}

    @staticmethod
    def _download_json(url: str) -> dict:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)

    @staticmethod
    def _download_file(url: str, destination: Path) -> None:
        temp = destination.with_suffix(destination.suffix + ".download")
        try:
            with urllib.request.urlopen(url, timeout=30) as response, temp.open("wb") as output:
                while chunk := response.read(65536):
                    output.write(chunk)
            temp.replace(destination)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()


class _ProgressWriter(io.TextIOBase):
    def __init__(self, callback):
        self.callback = callback
        self.buffer = ""

    def write(self, text):
        self.buffer += text
        for value in re.findall(r"\((\d+) %\)", self.buffer):
            self.callback(min(90, 10 + int(value) * 0.8))
        self.buffer = self.buffer[-200:]
        return len(text)


class FirmwareUpdater:
    def __init__(self, manager, catalog: FirmwareCatalog, notify):
        self.manager = manager
        self.catalog = catalog
        self.notify = notify
        self.state = {"state": "idle", "progress": 0, "message": ""}
        self._lock = threading.Lock()

    def start(self, device_id: str, role: str, port: str | None = None) -> None:
        with self._lock:
            if self.state["state"] in {"preparing", "flashing", "erasing", "restarting"}:
                raise RuntimeError("Another device is already being updated.")
            session = self.manager.session_for_device(device_id) if device_id else self.manager.session_for_port(port or "")
            if not session:
                raise RuntimeError("That device is no longer connected.")
            if role not in {"robot", "wireless_controller"}:
                raise RuntimeError("Choose whether this board is a robot or wireless controller.")
            if session.info and session.info.role != role:
                raise RuntimeError("The selected firmware does not match this device.")
            original_id = session.info.device_id if session.info else None
            self.state = {
                "state": "preparing", "progress": 2,
                "message": "Preparing the update…", "deviceId": original_id, "role": role,
            }
        self.notify()
        provisioning = session.info is None
        threading.Thread(
            target=self._run,
            args=(session, role, original_id, provisioning),
            daemon=True,
        ).start()

    def erase(self, device_id: str) -> None:
        with self._lock:
            if self.state["state"] in {"preparing", "flashing", "erasing", "restarting"}:
                raise RuntimeError("Another device operation is already in progress.")
            session = self.manager.session_for_device(device_id)
            if not session or not session.info:
                raise RuntimeError("That device is no longer connected.")
            self.state = {
                "state": "preparing", "progress": 2,
                "message": "Preparing to erase the board…",
                "deviceId": session.info.device_id,
                "role": session.info.role,
                "operation": "erase",
            }
        self.notify()
        threading.Thread(target=self._run_erase, args=(session,), daemon=True).start()

    def _set(self, state: str, progress: int, message: str, **extra) -> None:
        with self._lock:
            self.state.update(state=state, progress=progress, message=message, **extra)
        self.notify()

    def _run(self, session, role: str, original_id: str | None, provisioning: bool) -> None:
        port = session.port.device
        physical_key = session.port.physical_key
        expected = None
        try:
            entry, image = self.catalog.obtain(role, provisioning=provisioning)
            offset_key = "provisioning_offset" if provisioning else "offset"
            expected_offset = "0x0" if provisioning else "0x10000"
            offset = entry.get(offset_key)
            if entry.get("chip") != "esp32c3" or offset != expected_offset:
                raise RuntimeError("This firmware package is not compatible with this board.")
            expected = entry["version"]
            self._set("flashing", 10, "Installing firmware. Keep the USB cable connected.")
            self.manager.pause_for_update(port)
            self._flash(port, offset, image)
            self._set("restarting", 94, "Restarting and checking the device…")
        except Exception as exc:
            self.manager.resume_after_update(port)
            # Native USB disappears as soon as an ESP32-C3 resets. Some hosts
            # report that expected post-write disappearance as a serial error
            # even though the image was installed successfully. The device's
            # identity and reported version are the authoritative result.
            if expected and self._wait_for_expected(
                role, expected, original_id, physical_key, timeout=8
            ):
                self._set(
                    "complete", 100,
                    f"Update complete. Firmware {expected} is installed.",
                    version=expected,
                )
                return
            self._set("failed", 0, self._friendly_error(exc))
            return
        self.manager.resume_after_update(port)
        if self._wait_for_expected(role, expected, original_id, physical_key, timeout=12):
            self._set(
                "complete", 100,
                f"Update complete. Firmware {expected} is installed.",
                version=expected,
            )
            return
        self._set(
            "failed", 0,
            "The firmware was installed, but Mira could not confirm the restart. Unplug the device, reconnect it, and try again.",
        )

    def _wait_for_expected(
        self,
        role: str,
        expected: str,
        original_id: str | None,
        physical_key: str,
        timeout: float,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if original_id:
                replacement = self.manager.session_for_device(original_id)
            else:
                replacement = next(
                    (
                        candidate for candidate in self.manager.connected_sessions()
                        if candidate.info
                        and candidate.info.role == role
                        and candidate.info.firmware == expected
                        and candidate.port.physical_key == physical_key
                    ),
                    None,
                )
            if replacement and replacement.info and replacement.info.firmware == expected:
                return True
            time.sleep(0.25)
        return False

    def _run_erase(self, session) -> None:
        port = session.port.device
        physical_key = session.port.physical_key
        command_finished = False
        try:
            self._set("erasing", 15, "Erasing firmware and saved settings. Keep the USB cable connected.")
            self.manager.pause_for_update(port)
            self._erase_flash(port)
            command_finished = True
            self._set("restarting", 94, "Restarting and checking the board…")
        except Exception as exc:
            self.manager.resume_after_update(port)
            if self._wait_for_unprogrammed(physical_key, timeout=8):
                self._set(
                    "complete", 100,
                    "Board erased. Choose whether to program it as a Robot or Wireless board.",
                    operation="erase",
                )
                return
            self._set("failed", 0, self._friendly_error(exc), operation="erase")
            return
        finally:
            if command_finished:
                self.manager.resume_after_update(port)

        if self._wait_for_unprogrammed(physical_key, timeout=12):
            self._set(
                "complete", 100,
                "Board erased. Choose whether to program it as a Robot or Wireless board.",
                operation="erase",
            )
            return
        self._set(
            "complete", 100,
            "Board erased. Unplug and reconnect it to choose new firmware.",
            operation="erase",
        )

    def _wait_for_unprogrammed(self, physical_key: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            replacement = self.manager.session_for_physical_key(physical_key)
            if replacement and replacement.state == "unrecognized":
                return True
            time.sleep(0.25)
        return False

    def _flash(self, port: str, offset: str, image: Path) -> None:
        writer = _ProgressWriter(lambda progress: self._set(
            "flashing", int(progress), "Installing firmware. Keep the USB cable connected."
        ))
        args = [
            "--chip", "esp32c3", "--port", port, "--baud", "460800",
            "write-flash", offset, str(image),
        ]
        self._run_esptool(args, writer, "The device did not accept the firmware.")

    def _erase_flash(self, port: str) -> None:
        writer = _ProgressWriter(lambda _progress: self._set(
            "erasing", 60, "Erasing firmware and saved settings. Keep the USB cable connected."
        ))
        args = ["--chip", "esp32c3", "--port", port, "erase-flash"]
        self._run_esptool(args, writer, "The board could not be erased.")

    @staticmethod
    def _run_esptool(args: list[str], writer: _ProgressWriter, failure_message: str) -> None:
        last_error = None
        for attempt in range(3):
            # Closing a serial handle is asynchronous in some macOS and Windows
            # USB drivers. Give the OS time to release it, and also tolerate a
            # blank ESP32-C3 briefly re-enumerating while it boot-loops.
            time.sleep(0.35 if attempt == 0 else 0.8)
            try:
                FirmwareUpdater._run_esptool_once(args, writer, failure_message)
                return
            except RuntimeError as exc:
                last_error = exc
                logging.warning(
                    "Board programming attempt %s failed: %s; output tail: %s",
                    attempt + 1, exc, writer.buffer.replace("\r", " ").replace("\n", " "),
                )
        raise last_error or RuntimeError(failure_message)

    @staticmethod
    def _run_esptool_once(args: list[str], writer: _ProgressWriter, failure_message: str) -> None:
        # A normal terminal launch can safely isolate esptool in a child Python
        # process. This avoids stale import state and lets the tool own its
        # serial lifecycle. PyInstaller apps use the bundled module in-process.
        if not getattr(sys, "frozen", False):
            try:
                process = subprocess.Popen(
                    [sys.executable, "-m", "esptool", *args],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                raise RuntimeError(
                    "Mira could not start the board programming tool. Restart Mira and try again."
                ) from exc
            if process.stdout:
                for line in process.stdout:
                    writer.write(line)
            if process.wait() != 0:
                raise RuntimeError(failure_message)
            return

        try:
            import esptool
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                esptool.main(args)
        except ImportError as exc:
            raise RuntimeError(
                "Mira could not start the board programming tool. Reinstall Mira and try again."
            ) from exc
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise RuntimeError(failure_message) from exc

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        text = str(exc)
        if "connect" in text.lower() or "boot" in text.lower():
            return "Mira could not start update mode. Hold BOOT, tap RESET, release BOOT, then try again."
        return text or "The update did not finish. Reconnect the device and try again."
