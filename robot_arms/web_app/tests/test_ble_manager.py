import asyncio
import unittest
from types import SimpleNamespace

from ble_manager import BleManager, parse_device_info


class DeviceInfoTests(unittest.TestCase):
    def test_parses_ble_identity_metadata(self):
        info = parse_device_info(
            "role=robot id=aa:bb:cc:dd:ee:ff firmware=0.6.0 protocol=2 hardware=esp32c3"
        )
        self.assertEqual(info.device_id, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(info.firmware, "0.6.0")
        self.assertEqual(info.protocol, 2)
        self.assertFalse(info.legacy)

    def test_rejects_non_mira_metadata(self):
        with self.assertRaises(ValueError):
            parse_device_info("role=controller protocol=2")


class NotificationTests(unittest.TestCase):
    def test_reassembles_lines_across_default_mtu_notifications(self):
        lines = []
        manager = BleManager(lambda session, line: lines.append((session.info.device_id, line)), lambda: None)
        info = parse_device_info(
            "role=robot id=AA:BB:CC:DD:EE:FF firmware=0.6.0 protocol=2 hardware=esp32c3"
        )
        session = SimpleNamespace(info=info, rx_buffer="")
        manager.sessions["robot"] = session

        manager._notification("robot", bytearray(b"Calibration: B=1.0 "))
        manager._notification("robot", bytearray(b"S=2.0 E=3.0 G=4.0\nOK"))
        manager._notification("robot", bytearray(b"\n"))

        self.assertEqual(lines, [
            ("AA:BB:CC:DD:EE:FF", "Calibration: B=1.0 S=2.0 E=3.0 G=4.0"),
            ("AA:BB:CC:DD:EE:FF", "OK"),
        ])


if __name__ == "__main__":
    unittest.main()
