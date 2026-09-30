import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))


class AppPathsTests(unittest.TestCase):
    def test_data_directory_override(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"MIRA_DATA_DIR": directory}):
                import app_paths

                self.assertEqual(app_paths.user_data_dir(), Path(directory))


class DirectRobotStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MIRA_DATA_DIR": self.temp_dir.name})
        self.env.start()

        if "mira" in sys.modules:
            del sys.modules["mira"]
        self.mira = importlib.import_module("mira")
        self.mira.socketio.emit = mock.Mock()
        self.mira.name_map = {}
        self.mira.robots = {}
        self.mira.device_type = "master"

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def test_prompt_prefixed_mac_registers_direct_robot(self):
        self.mira.process_serial_line(
            "mira> [Swarm] Node MAC: AA:BB:CC:DD:EE:FF"
        )

        self.assertEqual(self.mira.device_type, "robot")
        self.assertIn("AA:BB:CC:DD:EE:FF", self.mira.robots)
        self.assertTrue(self.mira.robots["AA:BB:CC:DD:EE:FF"]["online"])

    def test_direct_commands_are_not_prefixed(self):
        writes = []
        self.mira.device_type = "robot"
        self.mira.serial_write = lambda command: writes.append(command)

        self.mira.ws_send_command({"target": "Robot 1", "command": "home"})

        self.assertEqual(writes, ["home"])

    def test_direct_calibration_reply_is_emitted_as_values(self):
        self.mira.process_serial_line(
            "Calibration: B=-12.5 S=4.0 E=30.5 G=-1.0"
        )

        self.mira.socketio.emit.assert_any_call("calibration_values", {
            "base": -12.5,
            "shoulder": 4.0,
            "elbow": 30.5,
            "grip": -1.0,
        })

    def test_wireless_calibration_reply_includes_robot_target(self):
        self.mira.process_serial_line(
            "R2> Calibration: B=1.0 S=2.0 E=3.0 G=4.0"
        )

        self.mira.socketio.emit.assert_any_call("calibration_values", {
            "base": 1.0,
            "shoulder": 2.0,
            "elbow": 3.0,
            "grip": 4.0,
            "target": "R2",
        })


class SerialDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MIRA_DATA_DIR": self.temp_dir.name})
        self.env.start()
        if "mira" in sys.modules:
            del sys.modules["mira"]
        self.mira = importlib.import_module("mira")

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def test_ignores_unrelated_fallback_port(self):
        port = mock.Mock(
            device="/dev/cu.debug-console",
            description="n/a",
            hwid="n/a",
            vid=None,
        )
        with mock.patch.object(
            self.mira.serial.tools.list_ports, "comports", return_value=[port]
        ):
            self.assertIsNone(self.mira.auto_detect_port())

    def test_detects_usb_modem(self):
        port = mock.Mock(
            device="/dev/cu.usbmodem101",
            description="USB JTAG/serial debug unit",
            hwid="USB VID:PID=303A:1001",
            vid=0x303A,
        )
        with mock.patch.object(
            self.mira.serial.tools.list_ports, "comports", return_value=[port]
        ):
            self.assertEqual(self.mira.auto_detect_port(), "/dev/cu.usbmodem101")


if __name__ == "__main__":
    unittest.main()
