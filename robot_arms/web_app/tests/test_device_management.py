import importlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

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
            "MIRA_DEVICE ab12 role=robot id=aa:bb:cc:dd:ee:ff firmware=0.5.0 protocol=1 hardware=esp32c3",
            "ab12",
        )
        self.assertEqual(info.role, "robot")
        self.assertEqual(info.device_id, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(info.firmware, "0.5.0")
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

    def test_invalid_flash_is_exposed_for_provisioning(self):
        changes = []
        manager = DeviceManager(lambda *_: None, lambda: changes.append(True))
        handle = FakeHandle()
        session = DeviceSession(PortDescriptor("COM4"), handle, "nonce")
        manager.sessions["COM4"] = session

        manager._identify(session, "invalid header: 0xffffffff")

        self.assertEqual(session.state, "unrecognized")
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


class FirmwareCatalogTests(unittest.TestCase):
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
        with self.assertRaisesRegex(RuntimeError, "blank board"):
            catalog.obtain("robot", provisioning=True)


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


if __name__ == "__main__":
    unittest.main()
