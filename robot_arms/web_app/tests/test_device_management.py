import importlib
import binascii
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from board_inspector import (
    APP_DESCRIPTION_MAGIC,
    BoardInspector,
    BoardInspection,
    Partition,
    parse_app_fingerprint,
    parse_partition_table,
    selected_app_partition,
)
from device_manager import DeviceInfo, DeviceManager, DeviceSession, PortDescriptor, is_candidate, parse_device_info
from firmware_update import FirmwareCatalog, FirmwareUpdater, version_tuple


class FakeHandle:
    def __init__(self):
        self.is_open = True
        self.writes = []

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        pass

    def close(self):
        self.is_open = False


class DeviceProtocolTests(unittest.TestCase):
    def test_parses_nonce_bound_identity(self):
        info = parse_device_info(
            "MIRA_DEVICE ab12 role=robot id=aa:bb:cc:dd:ee:ff firmware=0.7.0 "
            "protocol=3 hardware=esp32c3 name=Mira%20Blue",
            "ab12",
        )
        self.assertEqual(info.role, "robot")
        self.assertEqual(info.device_id, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(info.firmware, "0.7.0")
        self.assertEqual(info.name, "Mira Blue")
        self.assertIsNone(parse_device_info(
            "MIRA_DEVICE stale role=robot id=AA:BB:CC:DD:EE:FF", "current"
        ))

    def test_candidate_metadata_is_only_a_filter(self):
        self.assertTrue(is_candidate(PortDescriptor("COM4", vid=0x303A)))
        self.assertTrue(is_candidate(PortDescriptor("/dev/cu.usbserial-1")))
        self.assertFalse(is_candidate(PortDescriptor("/dev/cu.Bluetooth-Incoming-Port")))

    def test_remove_closes_handle_and_notifies(self):
        changes = []
        manager = DeviceManager(lambda *_: None, lambda: changes.append(True))
        handle = FakeHandle()
        session = DeviceSession(PortDescriptor("COM4"), handle, "nonce")
        session.info = DeviceInfo("robot", "AA:BB:CC:DD:EE:FF", "0.5.0", 1)
        session.state = "connected"
        manager.sessions["COM4"] = session

        manager._remove("COM4", "unplugged")

        self.assertFalse(handle.is_open)
        self.assertNotIn("COM4", manager.sessions)
        self.assertTrue(changes)

    def test_health_timeout_removes_a_stale_new_protocol_device(self):
        manager = DeviceManager(lambda *_: None, lambda: None)
        handle = FakeHandle()
        session = DeviceSession(PortDescriptor("COM4"), handle, "nonce")
        session.info = DeviceInfo("robot", "AA:BB:CC:DD:EE:FF", "0.5.0", 1)
        session.state = "connected"
        session.last_identity_at = time.monotonic() - 10
        manager.sessions["COM4"] = session

        manager._health_check()

        self.assertNotIn("COM4", manager.sessions)
        self.assertFalse(handle.is_open)

    def test_invalid_boot_log_is_verified_before_provisioning(self):
        changes = []
        inspector = mock.Mock()
        inspector.inspect.return_value = BoardInspection("corrupt", mac="AA:BB:CC:DD:EE:FF")
        manager = DeviceManager(
            lambda *_: None, lambda: changes.append(True), inspector=inspector
        )
        handle = FakeHandle()
        session = DeviceSession(PortDescriptor("COM4"), handle, "nonce")
        manager.sessions["COM4"] = session

        manager._identify(session, "invalid header: 0xffffffff")
        deadline = time.monotonic() + 1
        while session.state == "inspecting" and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(session.state, "unrecognized")
        self.assertEqual(session.classification, "corrupt")
        inspector.inspect.assert_called_once()
        self.assertFalse(handle.is_open)
        self.assertTrue(changes)

    def test_blank_board_survives_brief_usb_reenumeration(self):
        manager = DeviceManager(lambda *_: None, lambda: None, port_lister=lambda: [])
        handle = FakeHandle()
        handle.close()
        session = DeviceSession(PortDescriptor("COM4", serial_number="board-1"), handle, "nonce")
        session.state = "unrecognized"
        manager.sessions["COM4"] = session

        manager.scan_once()

        self.assertIn("COM4", manager.sessions)

    def test_silent_mira_image_is_classified_from_flash_not_usb_history(self):
        inspector = mock.Mock()
        inspector.inspect.return_value = BoardInspection(
            "mira", mac="AA:BB:CC:DD:EE:FF", role="robot", firmware="0.5.0"
        )
        manager = DeviceManager(lambda *_: None, lambda: None, inspector=inspector)
        descriptor = PortDescriptor("COM4", serial_number="board-1")
        retry = DeviceSession(descriptor, FakeHandle(), "second")
        manager.sessions["COM4"] = retry
        manager._probe_failed(retry)
        deadline = time.monotonic() + 1
        while retry.state == "inspecting" and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(retry.state, "repair")
        self.assertNotEqual(retry.state, "unrecognized")
        self.assertEqual(retry.info.role, "robot")
        self.assertEqual(retry.info.firmware, "0.5.0")
        self.assertTrue(retry.requires_factory)

    def test_reusing_a_usb_socket_does_not_reuse_the_previous_board_identity(self):
        inspector = mock.Mock()
        inspector.inspect.return_value = BoardInspection("erased", mac="11:22:33:44:55:66")
        manager = DeviceManager(lambda *_: None, lambda: None, inspector=inspector)
        descriptor = PortDescriptor("COM4", location="same-usb-socket")
        old = DeviceSession(descriptor, FakeHandle(), "old")
        old.info = DeviceInfo("robot", "AA:BB:CC:DD:EE:FF", "0.5.2", 1)
        old.state = "connected"
        manager.sessions["COM4"] = old
        manager._remove("COM4", "unplugged")

        replacement = DeviceSession(descriptor, FakeHandle(), "new")
        manager.sessions["COM4"] = replacement
        manager._probe_failed(replacement)
        deadline = time.monotonic() + 1
        while replacement.state == "inspecting" and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(replacement.state, "unrecognized")
        self.assertEqual(replacement.classification, "erased")
        self.assertIsNone(replacement.info)

    def test_update_reserves_the_physical_board_across_port_renames(self):
        replacement = SimpleNamespace(
            device="COM9", description="ESP32-C3", hwid="USB VID:PID=303A:1001",
            vid=0x303A, pid=0x1001, serial_number="board-1", location="1-2",
        )
        serial_factory = mock.Mock()
        manager = DeviceManager(
            lambda *_: None,
            lambda: None,
            serial_factory=serial_factory,
            port_lister=lambda: [replacement],
        )
        session = DeviceSession(
            PortDescriptor("COM4", vid=0x303A, pid=0x1001, serial_number="board-1"),
            FakeHandle(),
            "nonce",
        )
        session.info = DeviceInfo("robot", "AA:BB:CC:DD:EE:FF", "0.4.0", 0, legacy=True)
        session.state = "connected"
        manager.sessions["COM4"] = session

        descriptor = manager.pause_for_update("COM4")
        manager.scan_once()

        self.assertEqual(descriptor.physical_key, "board-1")
        serial_factory.assert_not_called()

        manager.resume_after_update("COM4", descriptor.physical_key)
        manager.scan_once()
        serial_factory.assert_called_once_with("COM9", 115200, timeout=0.15)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MIRA_DATA_DIR": self.temp_dir.name})
        self.env.start()
        if "mira" in sys.modules:
            del sys.modules["mira"]
        self.mira = importlib.import_module("mira")
        self.writes = []
        self.fake_manager = mock.Mock()
        self.fake_manager.write.side_effect = lambda port, command: self.writes.append((port, command)) or True
        self.original_manager = self.mira.device_manager
        self.mira.device_manager = self.fake_manager
        self.mira.robots = {}

    def tearDown(self):
        self.mira.device_manager = self.original_manager
        self.env.stop()
        self.temp_dir.cleanup()

    def test_direct_path_wins_when_robot_is_also_wireless(self):
        mac = "AA:BB:CC:DD:EE:FF"
        self.mira.robots[mac] = {
            "mac": mac, "name": "Mira", "masterName": "R1",
            "endpoints": {
                "usb:COM4": {"transport": "usb", "port": "COM4"},
                "wireless:COM5": {"transport": "wireless", "port": "COM5"},
            },
        }
        self.assertTrue(self.mira._route_command(mac, "home"))
        self.assertEqual(self.writes, [("COM4", "home")])

    def test_simple_wireless_all_uses_one_synchronized_broadcast(self):
        for suffix in ("01", "02"):
            mac = f"AA:BB:CC:DD:EE:{suffix}"
            self.mira.robots[mac] = {
                "mac": mac, "name": mac, "masterName": mac,
                "endpoints": {
                    "wireless:COM5": {"transport": "wireless", "port": "COM5"},
                },
            }
        self.assertTrue(self.mira._route_command("all", "gesture dance"))
        self.assertEqual(self.writes, [("COM5", "gesture dance")])

    def test_rename_is_written_to_robot_flash_over_the_selected_path(self):
        mac = "AA:BB:CC:DD:EE:FF"
        self.mira.robots[mac] = {
            "mac": mac, "name": "Old name", "masterName": "R1",
            "endpoints": {
                "wireless:COM5": {"transport": "wireless", "port": "COM5"},
            },
        }

        response = self.mira.app.test_client().post(
            "/api/robots/rename", json={"mac": mac, "name": "Art Bot"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.writes, [("COM5", f"@{mac} name set Art Bot")])
        self.assertEqual(self.mira.robots[mac]["name"], "Art Bot")


class BoardInspectionParsingTests(unittest.TestCase):
    @staticmethod
    def partition_entry(part_type, subtype, offset, size, label):
        return struct.pack(
            "<HBBII16sI",
            0x50AA,
            part_type,
            subtype,
            offset,
            size,
            label.encode().ljust(16, b"\0"),
            0,
        )

    def test_partition_table_checksum_is_validated(self):
        entries = b"".join([
            self.partition_entry(1, 0, 0xE000, 0x2000, "otadata"),
            self.partition_entry(0, 0x10, 0x10000, 0x140000, "app0"),
        ])
        checksum = b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(entries).digest()
        table = (entries + checksum).ljust(0x1000, b"\xff")

        parsed = parse_partition_table(table)
        self.assertEqual([part.label for part in parsed], ["otadata", "app0"])
        damaged = bytearray(table)
        damaged[10] ^= 1
        self.assertIsNone(parse_partition_table(bytes(damaged)))

    def test_application_fingerprint_requires_c3_and_app_description_magic(self):
        fingerprint = bytes(range(32))
        image = bytearray(b"\0" * 0x120)
        image[0] = 0xE9
        struct.pack_into("<H", image, 12, 5)
        struct.pack_into("<I", image, 0x20, APP_DESCRIPTION_MAGIC)
        image[0xB0:0xD0] = fingerprint

        self.assertEqual(parse_app_fingerprint(bytes(image)), fingerprint.hex())
        image[0] = 0
        self.assertIsNone(parse_app_fingerprint(bytes(image)))

    def test_ota_metadata_selects_the_active_application(self):
        partitions = [
            Partition(1, 0, 0xE000, 0x2000, "otadata"),
            Partition(0, 0x10, 0x10000, 0x140000, "app0"),
            Partition(0, 0x11, 0x150000, 0x140000, "app1"),
        ]
        flash = bytearray(b"\xff" * 0x9000)
        sequence = 2
        checksum = binascii.crc32(struct.pack("<I", sequence), 0xFFFFFFFF) & 0xFFFFFFFF
        entry = struct.pack("<I20sII", sequence, b"\0" * 20, 2, checksum)
        flash[0x6000:0x6020] = entry

        self.assertEqual(selected_app_partition(partitions, bytes(flash)).label, "app1")

    def test_inspector_recognizes_a_published_mira_image_without_running_it(self):
        fingerprint = bytes(range(32))
        partition_entries = b"".join([
            self.partition_entry(1, 0, 0xE000, 0x2000, "otadata"),
            self.partition_entry(0, 0x10, 0x10000, 0x140000, "app0"),
        ])
        checksum = b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(partition_entries).digest()
        initial = bytearray(b"\xff" * 0x8120)
        initial[:len(partition_entries + checksum)] = partition_entries + checksum
        app = memoryview(initial)[0x8000:0x8120]
        app[0] = 0xE9
        struct.pack_into("<H", app, 12, 5)
        struct.pack_into("<I", app, 0x20, APP_DESCRIPTION_MAGIC)
        app[0xB0:0xD0] = fingerprint
        inspector = BoardInspector(lambda value: {
            "role": "robot", "version": "0.5.9"
        } if value == fingerprint.hex() else None)

        def fake_read(_resolver, _address, _size, destination):
            destination.write_bytes(initial)
            return "Connected to ESP32-C3\nMAC: aa:bb:cc:dd:ee:ff"

        with mock.patch.object(inspector, "_read_flash", side_effect=fake_read):
            result = inspector.inspect(lambda: "COM4")

        self.assertEqual(result.kind, "mira")
        self.assertEqual(result.role, "robot")
        self.assertEqual(result.firmware, "0.5.9")
        self.assertEqual(result.mac, "AA:BB:CC:DD:EE:FF")

    def test_inspector_explains_when_another_program_owns_the_port(self):
        failed = SimpleNamespace(returncode=2, stdout="Could not open COM4: Resource busy")
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "board_inspector.subprocess.run", return_value=failed
        ), mock.patch("board_inspector.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "Another program is using"):
                BoardInspector._read_flash(
                    lambda: "COM4", 0x8000, 0x1000, Path(directory) / "flash.bin"
                )


class FirmwareCatalogTests(unittest.TestCase):
    def test_refresh_reads_the_public_manifest_from_latest_github_release(self):
        release = {
            "assets": [
                {
                    "name": "mira-firmware-manifest.json",
                    "browser_download_url": "https://downloads.example/manifest",
                },
                {
                    "name": "mira-robot-0.5.0.bin",
                    "browser_download_url": "https://downloads.example/robot",
                },
            ]
        }
        manifest = {"schema": 1, "robot": {"version": "0.5.0"}}

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "firmware_update.user_data_dir", return_value=Path(temp_dir)
        ), mock.patch(
            "firmware_update.urllib.request.urlopen",
            side_effect=[io.BytesIO(json.dumps(release).encode()), io.BytesIO(json.dumps(manifest).encode())],
        ) as urlopen:
            catalog = FirmwareCatalog()
            catalog.manifest = {}
            result = catalog.refresh(force=True)

        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(result["robot"]["version"], "0.5.0")
        self.assertIn("mira-robot-0.5.0.bin", result["_assets"])

    def test_online_manifest_cannot_downgrade_bundled_firmware(self):
        catalog = FirmwareCatalog()
        catalog.manifest = {
            "schema": 2,
            "robot": {"version": "0.5.2", "asset": "robot-052.bin"},
        }
        merged = catalog._merge_manifests(
            catalog.manifest,
            {"schema": 1, "robot": {"version": "0.5.0", "asset": "robot-050.bin"}},
        )

        self.assertEqual(merged["robot"]["version"], "0.5.2")
        self.assertEqual(merged["robot"]["asset"], "robot-052.bin")

    def test_semantic_versions_are_numeric(self):
        self.assertGreater(version_tuple("0.10.0"), version_tuple("0.9.9"))

    def test_legacy_device_always_gets_migration_offer(self):
        catalog = FirmwareCatalog()
        catalog.manifest = {"robot": {"version": "0.5.0"}}
        self.assertTrue(catalog.update_available("robot", None, legacy=True))
        self.assertFalse(catalog.update_available("robot", "0.5.0", legacy=False))

    def test_blank_board_requires_factory_image(self):
        catalog = FirmwareCatalog()
        catalog.manifest = {"robot": {
            "version": "0.5.0", "asset": "app.bin", "sha256": "abc"
        }}
        with self.assertRaisesRegex(RuntimeError, "new board"):
            catalog.obtain("robot", provisioning=True)

    def test_deployed_robot_fingerprints_are_recognized_without_network(self):
        catalog = FirmwareCatalog()
        known = catalog.identify_fingerprint(
            "46893ffebaa5e8cb74c2dac5e5995131294ee66da8aa95fefcf9bb67570fdaf9"
        )

        self.assertEqual(known, {"role": "robot", "version": "0.5.0"})


class FirmwareUpdaterTests(unittest.TestCase):
    def test_erase_requires_an_identified_connected_device(self):
        manager = mock.Mock()
        manager.session_for_device.return_value = None
        updater = FirmwareUpdater(manager, mock.Mock(), lambda: None)

        with self.assertRaisesRegex(RuntimeError, "no longer connected"):
            updater.erase("AA:BB:CC:DD:EE:FF")

    def test_erase_starts_as_an_explicit_device_operation(self):
        manager = mock.Mock()
        session = DeviceSession(PortDescriptor("COM4"), FakeHandle(), "nonce")
        session.info = DeviceInfo("robot", "AA:BB:CC:DD:EE:FF", "0.5.0", 1)
        session.state = "connected"
        manager.session_for_device.return_value = session
        updater = FirmwareUpdater(manager, mock.Mock(), lambda: None)

        with mock.patch("firmware_update.threading.Thread") as thread:
            updater.erase(session.info.device_id)

        self.assertEqual(updater.state["operation"], "erase")
        self.assertEqual(updater.state["state"], "preparing")
        thread.return_value.start.assert_called_once()

    def test_repair_uses_a_complete_factory_image(self):
        manager = mock.Mock()
        session = DeviceSession(PortDescriptor("COM4"), FakeHandle(), "nonce")
        session.info = DeviceInfo("robot", "AA:BB:CC:DD:EE:FF", "0.5.2", 1)
        session.state = "repair"
        session.requires_factory = True
        manager.session_for_device.return_value = session
        updater = FirmwareUpdater(manager, mock.Mock(), lambda: None)

        with mock.patch("firmware_update.threading.Thread") as thread:
            updater.start(session.info.device_id, "robot")

        self.assertTrue(thread.call_args.kwargs["args"][3])

    def test_programming_retries_transient_serial_handoff_failures(self):
        writer = mock.Mock()
        writer.buffer = "port temporarily unavailable"
        with mock.patch("firmware_update.time.sleep"), mock.patch.object(
            FirmwareUpdater,
            "_run_esptool_once",
            side_effect=[RuntimeError("busy"), RuntimeError("missing"), None],
        ) as run_once:
            FirmwareUpdater._run_esptool([], writer, "failed")

        self.assertEqual(run_once.call_count, 3)

    def test_programming_retry_follows_a_renamed_usb_port(self):
        writer = mock.Mock()
        writer.buffer = "port disappeared during reset"
        ports = iter(["COM4", "COM9"])
        with mock.patch("firmware_update.time.sleep"), mock.patch.object(
            FirmwareUpdater,
            "_run_esptool_once",
            side_effect=[RuntimeError("missing"), None],
        ) as run_once:
            FirmwareUpdater._run_esptool(
                ["--chip", "esp32c3", "--port", "COM4", "write-flash"],
                writer,
                "failed",
                lambda: next(ports),
            )

        self.assertEqual(run_once.call_args_list[0].args[0][3], "COM4")
        self.assertEqual(run_once.call_args_list[1].args[0][3], "COM9")

    def test_programming_recovery_slows_down_then_uses_rom_bootloader(self):
        writer = mock.Mock()
        writer.buffer = ""
        with mock.patch("firmware_update.time.sleep"), mock.patch.object(
            FirmwareUpdater,
            "_run_esptool_once",
            side_effect=[RuntimeError("first"), RuntimeError("second"), None],
        ) as run_once:
            FirmwareUpdater._run_esptool(
                [
                    "--chip", "esp32c3", "--port", "COM4", "--baud", "460800",
                    "write-flash", "0x0", "factory.bin",
                ],
                writer,
                "failed",
            )

        second_attempt = run_once.call_args_list[1].args[0]
        final_attempt = run_once.call_args_list[2].args[0]
        self.assertEqual(second_attempt[second_attempt.index("--baud") + 1], "115200")
        self.assertEqual(final_attempt[final_attempt.index("--baud") + 1], "115200")
        self.assertLess(final_attempt.index("--no-stub"), final_attempt.index("write-flash"))

    def test_programming_failure_explains_how_to_enter_programming_mode(self):
        message = FirmwareUpdater._programming_error(
            "Fatal error: Failed to connect: No serial data received.",
            "The device did not accept the firmware.",
        )

        self.assertIn("Hold BOOT", message)
        self.assertNotIn("did not accept", message)

    def test_force_is_not_suggested_for_a_security_protected_board(self):
        message = FirmwareUpdater._programming_error(
            "ESP32-C3 is in Secure Download Mode; security check failed",
            "The device did not accept the firmware.",
        )

        self.assertIn("security settings", message)
        self.assertNotIn("BOOT", message)


if __name__ == "__main__":
    unittest.main()
