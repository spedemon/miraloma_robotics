import re
import math
import json
import unittest
from pathlib import Path


ROBOT_ROOT = Path(__file__).resolve().parents[2] / "robotarm_mcu"
CONFIG = (ROBOT_ROOT / "include" / "config.h").read_text()
SMOOTH_H = (ROBOT_ROOT / "lib" / "SmoothMover" / "SmoothMover.h").read_text()
SMOOTH_CPP = (ROBOT_ROOT / "lib" / "SmoothMover" / "SmoothMover.cpp").read_text()
CONSOLE_CPP = (ROBOT_ROOT / "lib" / "SerialConsole" / "SerialConsole.cpp").read_text()
IDENTITY_CPP = (ROBOT_ROOT / "lib" / "RobotIdentity" / "RobotIdentity.cpp").read_text()
SWARM_CPP = (ROBOT_ROOT / "lib" / "SwarmNode" / "SwarmNode.cpp").read_text()
BLE_CPP = (ROBOT_ROOT / "lib" / "BleTransport" / "BleTransport.cpp").read_text()
APP_JS = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text()


class FirmwareTrackingTests(unittest.TestCase):
    def test_robot_firmware_is_version_070(self):
        self.assertRegex(CONFIG, r'MIRA_FIRMWARE_VERSION\s+"0\.7\.0"')
        self.assertRegex(CONFIG, r'MIRA_PROTOCOL_VERSION\s+3')

    def test_bundled_manifest_tracks_the_firmware_protocol(self):
        manifest_path = Path(__file__).resolve().parents[1] / "firmware" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["robot"]["version"], "0.7.0")
        self.assertEqual(manifest["robot"]["protocol"], 3)

    def test_robot_name_is_persisted_and_published_by_every_transport(self):
        self.assertIn('preferences.putString(NAME_KEY, value)', IDENTITY_CPP)
        self.assertIn('" name=%s"', SWARM_CPP)
        self.assertIn('" hardware=esp32c3 name="', BLE_CPP)
        self.assertIn('cmd.startsWith("name set ")', CONSOLE_CPP)

    def test_tracking_command_is_atomic_and_silent_on_success(self):
        self.assertIn('cmd.startsWith("track ")', CONSOLE_CPP)
        command = self._function_body(CONSOLE_CPP, "SerialConsole::_cmdTrack")
        self.assertIn("_ctrl.solve(x, y, z, base, shoulder, elbow)", command)
        self.assertIn("_smooth.setTrackingTarget(base, shoulder, elbow)", command)
        self.assertNotIn("OK —", command)

    def test_retargeting_preserves_velocity(self):
        tracking = self._function_body(SMOOTH_CPP, "SmoothMover::setTrackingTarget")
        self.assertIn("if (!_trackingActive)", tracking)
        self.assertIn("_trackingVelocities[i] = 0.0f", tracking)
        self.assertLess(
            tracking.index("if (!_trackingActive)"),
            tracking.index("_trackingVelocities[i] = 0.0f"),
        )
        update = self._function_body(SMOOTH_CPP, "SmoothMover::_updateTracking")
        self.assertIn("_trackingVelocities[i] += velocityChange", update)
        self.assertIn("sqrtf(2.0f * _accel * absError)", update)

    def test_tracking_has_acceleration_limits_and_a_watchdog(self):
        self.assertIn("TRACKING_COMMAND_TIMEOUT_MS 300", CONFIG)
        update = self._function_body(SMOOTH_CPP, "SmoothMover::_updateTracking")
        self.assertIn("maxVelocityChange = _accel * dt", update)
        self.assertIn("now - _trackingLastCommandMs >= TRACKING_COMMAND_TIMEOUT_MS", update)
        self.assertIn("bool isTracking() const", SMOOTH_H)

    def test_ui_estimator_uses_the_firmware_motion_limits(self):
        self.assertRegex(CONFIG, r"SMOOTH_DEFAULT_MAX_SPEED\s+120\.0f")
        self.assertRegex(CONFIG, r"SMOOTH_DEFAULT_ACCEL\s+300\.0f")
        self.assertRegex(APP_JS, r"XYZ_MOTION_MAX_SPEED\s*=\s*120\.0")
        self.assertRegex(APP_JS, r"XYZ_MOTION_ACCEL\s*=\s*300\.0")

    def test_streamed_reversals_remain_speed_and_acceleration_limited(self):
        acceleration = 300.0
        max_speed = 120.0
        dt = 0.005
        position = 0.0
        velocity = 0.0
        target = 0.0

        for step_index in range(1200):
            # Browser targets arrive at 20 Hz and reverse repeatedly.
            if step_index % 10 == 0:
                target = 70.0 * math.sin(step_index * dt * 1.7)
            error = target - position
            desired_speed = min(max_speed, math.sqrt(2.0 * acceleration * abs(error)))
            desired_velocity = math.copysign(desired_speed, error) if abs(error) > 0.1 else 0.0
            previous_velocity = velocity
            velocity_change = max(
                -acceleration * dt,
                min(acceleration * dt, desired_velocity - velocity),
            )
            velocity += velocity_change
            position += velocity * dt

            self.assertLessEqual(abs(velocity), max_speed + 1e-9)
            self.assertLessEqual(
                abs(velocity - previous_velocity), acceleration * dt + 1e-9
            )

    @staticmethod
    def _function_body(source, name):
        match = re.search(rf"(?:void|bool)\s+{re.escape(name)}\([^)]*\)(?:\s+const)?\s*\{{", source)
        if not match:
            raise AssertionError(f"Could not find {name}")
        brace = source.index("{", match.start())
        depth = 0
        for index in range(brace, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[brace + 1:index]
        raise AssertionError(f"Could not find end of {name}")


if __name__ == "__main__":
    unittest.main()
