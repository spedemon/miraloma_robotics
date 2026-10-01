import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


WEB_APP_DIR = Path(__file__).resolve().parents[1]
INDEX = (WEB_APP_DIR / "static" / "index.html").read_text()
APP_JS = (WEB_APP_DIR / "static" / "app.js").read_text()
STYLE = (WEB_APP_DIR / "static" / "style.css").read_text()
ICONS_PATH = WEB_APP_DIR / "static" / "icons.svg"
ANDROID_ACTIVITY = (
    WEB_APP_DIR.parent / "android_app" / "app" / "src" / "main" / "java"
    / "org" / "miraloma" / "mira" / "MainActivity.java"
).read_text()


class ArmControlMarkupTests(unittest.TestCase):
    @staticmethod
    def _function_body(name):
        start = APP_JS.index(f"function {name}(")
        brace = APP_JS.index("{", start)
        depth = 0
        for index in range(brace, len(APP_JS)):
            if APP_JS[index] == "{":
                depth += 1
            elif APP_JS[index] == "}":
                depth -= 1
                if depth == 0:
                    return APP_JS[brace + 1:index]
        raise AssertionError(f"Could not find end of function {name}")

    def test_joint_sliders_share_the_same_scale_and_marks(self):
        for joint in ("base", "shoulder", "elbow"):
            slider = re.search(rf'<input[^>]+id="slider-{joint}"[^>]+>', INDEX).group(0)
            self.assertIn('min="-120"', slider)
            self.assertIn('max="120"', slider)

        tick_sets = re.findall(
            r'class="slider-ticks joint-slider-ticks"[^>]+', INDEX
        )
        self.assertEqual(len(tick_sets), 3)
        for ticks in tick_sets:
            self.assertIn('data-min="-120"', ticks)
            self.assertIn('data-max="120"', ticks)
            self.assertIn('data-tick="30"', ticks)
            self.assertIn('data-reversed="true"', ticks)

    def test_calibration_ranges_match_the_requested_adjustment_span(self):
        for joint in ("base", "shoulder", "elbow"):
            slider = re.search(rf'<input[^>]+id="cal-{joint}"[^>]+>', INDEX).group(0)
            self.assertIn('min="-90"', slider)
            self.assertIn('max="90"', slider)

        grip = re.search(r'<input[^>]+id="cal-grip"[^>]+>', INDEX).group(0)
        self.assertIn('min="-120"', grip)
        self.assertIn('max="120"', grip)

    def test_every_referenced_svg_icon_exists(self):
        tree = ET.parse(ICONS_PATH)
        namespace = "{http://www.w3.org/2000/svg}"
        available = {
            symbol.attrib["id"] for symbol in tree.findall(f".//{namespace}symbol")
        }
        referenced = set(re.findall(r'icons\.svg#([a-z0-9-]+)', INDEX))
        referenced.update(re.findall(r'iconSvg\("([a-z0-9-]+)"', APP_JS))
        referenced.update(re.findall(r'setSvgIcon\([^,]+, "([a-z0-9-]+)"', APP_JS))
        self.assertTrue(referenced)
        self.assertEqual(referenced - available, set())

    def test_branding_and_repository_link(self):
        self.assertIn("Miraloma Robotics", INDEX)
        self.assertIn("Robots Detected", INDEX)
        self.assertIn(
            'href="https://github.com/spedemon/miraloma_robotics"', INDEX
        )
        self.assertIn(
            "#if-calibration-cannot-make-the-robot-straight-or-preserve-full-motion",
            INDEX,
        )

    def test_android_uses_the_local_mobile_bridge(self):
        self.assertIn("window.MiraAndroid", INDEX)
        self.assertIn("/static/mobile_bridge.js", INDEX)
        bridge = (WEB_APP_DIR / "static" / "mobile_bridge.js").read_text()
        self.assertIn('window.io = function ()', bridge)
        self.assertIn('event === "send_command"', bridge)
        self.assertIn('window.MiraAndroid.api', bridge)

    def test_device_settings_can_connect_and_disconnect_bluetooth(self):
        settings = self._function_body("renderDeviceSettings")
        self.assertIn('device.transport === "ble"', settings)
        self.assertIn("connectBluetoothDevice", settings)
        self.assertIn("disconnectBluetoothDevice", settings)

    def test_help_explains_all_three_connection_methods(self):
        self.assertIn("Connect one of three ways", INDEX)
        for label in ("Bluetooth", "USB cable", "Radio"):
            self.assertRegex(INDEX, rf'<h3 class="title-with-mark">.*?{label}</h3>')

    def test_calibration_reveals_before_requesting_home(self):
        body = self._function_body("openCalibration")
        self.assertLess(body.index("revealCalibration();"), body.index("sendHome();"))
        self.assertLess(body.index("sendHome();"), body.index("loadCalibrationValues();"))
        self.assertIn("calibrationAtHome = false", body)

    def test_calibration_controls_stay_disabled_while_robot_is_homing(self):
        loading = self._function_body("setCalibrationControlsLoading")
        actions = self._function_body("updateCalibrationActionState")
        self.assertIn("loading || calibrationOpening", loading)
        self.assertIn("calibrationOpening || calibrationLoadPending", actions)

    def test_applying_calibration_does_not_issue_a_motion_command(self):
        body = self._function_body("calApply")
        self.assertIn("cal_set", body)
        self.assertNotIn('sendCommand("home")', body)
        self.assertNotIn("sendHome()", body)

    def test_apply_requires_preview_to_be_at_home(self):
        body = self._function_body("calApply")
        self.assertIn("!calibrationAtHome", body)
        grip_test = self._function_body("calGripTest")
        self.assertIn('position === "closed"', grip_test)

    def test_grip_calibration_keeps_an_exclusive_test_position(self):
        open_button = re.search(r'<button[^>]+id="cal-test-open"[^>]+>', INDEX).group(0)
        closed_button = re.search(r'<button[^>]+id="cal-test-closed"[^>]+>', INDEX).group(0)
        self.assertIn('data-position="open"', open_button)
        self.assertIn('aria-pressed="false"', open_button)
        self.assertIn('data-position="closed"', closed_button)
        self.assertIn('aria-pressed="true"', closed_button)
        slider_setup = self._function_body("initCalibrationSliders")
        self.assertIn('joint === "grip" ? calibrationGripTestPosition : "home"', slider_setup)
        self.assertIn('cal_preview ${joint} ${offset} ${pose}', slider_setup)
        grip_test = self._function_body("calGripTest")
        self.assertIn('cal_preview grip ${candidateOffset} ${position}', grip_test)
        self.assertNotIn("set grip", grip_test)

    def test_xyz_glide_uses_joint_limited_motion(self):
        cartesian_move = self._function_body("sendCartesianMove")
        self.assertIn('continuous ? "track" : "smmove"', cartesian_move)
        self.assertIn("sendCommand(`${command}", cartesian_move)
        self.assertNotIn("smset base", cartesian_move)

    def test_xyz_projection_click_and_drag_move_the_robot_live(self):
        plane_update = self._function_body("updateCartesianFromPlane")
        workspace_setup = self._function_body("initXYZWorkspace")
        live_move = self._function_body("scheduleLiveCartesianMove")
        self.assertIn("scheduleLiveCartesianMove();", plane_update)
        self.assertIn("scheduleLiveCartesianMove(true);", workspace_setup)
        self.assertIn("sendCartesianMove(false, true);", live_move)
        self.assertRegex(APP_JS, r"XYZ_LIVE_SEND_MS\s*=\s*50")
        self.assertRegex(APP_JS, r"XYZ_DRAG_FILTER_ALPHA\s*=\s*0\.42")

    def test_motion_is_always_glide_without_a_selector(self):
        self.assertNotIn('toggle-group-label">Motion', INDEX)
        self.assertNotIn('id="motion-smooth"', INDEX)
        self.assertNotIn('id="motion-instant"', INDEX)
        self.assertNotIn("motionType", APP_JS)
        self.assertNotIn("setMotionType", APP_JS)
        self.assertIn("smset ${joint} ${angle}", self._function_body("sendJointMove"))
        self.assertIn("smset grip ${grip}", self._function_body("sendGrip"))

    def test_xyz_workspace_has_three_draggable_projection_views(self):
        for plane in ("xy", "xz", "yz"):
            self.assertIn(f'id="xyz-plane-{plane}"', INDEX)
        self.assertIn('id="xyz-volume-canvas"', INDEX)
        workspace_setup = self._function_body("initXYZWorkspace")
        self.assertIn('canvas.addEventListener("pointerdown"', workspace_setup)
        self.assertIn('canvas.addEventListener("pointermove"', workspace_setup)

    def test_xyz_volume_supports_rotation_and_zoom(self):
        self.assertIn('id="xyz-volume-zoom-out"', INDEX)
        self.assertIn('id="xyz-volume-zoom-in"', INDEX)
        self.assertIn('id="xyz-volume-reset"', INDEX)
        workspace_setup = self._function_body("initXYZWorkspace")
        self.assertIn('volumeCanvas.addEventListener("pointermove"', workspace_setup)
        self.assertIn('volumeCanvas.addEventListener("wheel"', workspace_setup)
        self.assertRegex(APP_JS, r"XYZ_DEFAULT_VOLUME_ZOOM\s*=\s*1\.45")

    def test_xyz_volume_draws_an_articulated_estimated_robot(self):
        self.assertIn("Robot (estimated)", INDEX)
        geometry = self._function_body("xyzArmGeometry")
        schematic = self._function_body("drawXYZRobotSchematic")
        volume = self._function_body("drawXYZVolume")
        self.assertIn("shoulder", geometry)
        self.assertIn("elbow", geometry)
        self.assertIn("strokeSegment(base, shoulder", schematic)
        self.assertIn("strokeSegment(shoulder, elbow", schematic)
        self.assertIn("strokeSegment(elbow, end", schematic)
        self.assertIn("drawXYZRobotSchematic", volume)

    def test_estimated_robot_preserves_velocity_and_trails_target(self):
        step = self._function_body("stepXYZRobotJoint")
        move = self._function_body("sendCartesianMove")
        self.assertIn("XYZ_MOTION_ACCEL * dt", step)
        self.assertIn("velocity + velocityChange", step)
        self.assertIn("setXYZRobotTarget(solution.joints)", move)
        self.assertNotIn("lastValidCartesianTarget = { x, y, z }", move)

    def test_unreachable_xyz_target_stays_visible_but_cannot_move(self):
        cartesian_move = self._function_body("sendCartesianMove")
        workspace_update = self._function_body("updateXYZWorkspace")
        self.assertIn("if (!solution.valid)", cartesian_move)
        self.assertNotIn("restoreLastValidCartesianTarget", cartesian_move)
        self.assertIn("moveButton.disabled = !validation.valid", workspace_update)
        self.assertIn("reason.textContent", workspace_update)

    def test_unreachable_plane_click_uses_nearest_reachable_point(self):
        plane_update = self._function_body("updateCartesianFromPlane")
        nearest = self._function_body("nearestReachableTargetInPlane")
        workspace_update = self._function_body("updateXYZWorkspace")
        self.assertIn("nearestReachableTargetInPlane(key, moveTarget)", plane_update)
        self.assertIn("setCartesianInputPosition(moveTarget)", plane_update)
        self.assertIn("going to the nearest reachable position", plane_update)
        self.assertIn("definition.fixed", nearest)
        self.assertIn("solveCartesianTarget", nearest)
        self.assertIn("xyzPositionNotice", workspace_update)

    def test_xyz_inputs_are_numeric_and_share_firmware_limits(self):
        for axis, minimum, maximum in (("x", "-126", "126"), ("y", "-126", "126"), ("z", "0", "148")):
            field = re.search(rf'<input[^>]+id="slider-{axis}"[^>]+>', INDEX).group(0)
            self.assertIn('type="number"', field)
            self.assertIn(f'min="{minimum}"', field)
            self.assertIn(f'max="{maximum}"', field)

    def test_collapsed_console_header_fits_inside_the_viewport(self):
        self.assertIn("--console-height: 56px", STYLE)
        self.assertRegex(STYLE, r"\.app\s*\{[^}]*height:\s*100dvh")
        self.assertRegex(STYLE, r"\.main\s*\{[^}]*min-height:\s*0")
        self.assertRegex(
            STYLE,
            r"\.console-header\s*\{[^}]*min-height:\s*calc\(var\(--console-height\) - 2px\)",
        )
        self.assertRegex(
            STYLE,
            r"\.console\s*\{[^}]*min-height:\s*var\(--console-height\)[^}]*overflow:\s*hidden",
        )

    def test_mobile_shell_exposes_four_task_workspaces(self):
        workspace_buttons = re.findall(
            r'data-mobile-workspace="(move|animate|dances|robots)"', INDEX
        )
        self.assertEqual(workspace_buttons, ["move", "animate", "dances", "robots"])
        for workspace in ("move", "animate", "dances", "robots"):
            self.assertIn(f'data-workspace="{workspace}"', INDEX)
        self.assertIn("function setMobileWorkspace(workspace)", APP_JS)
        self.assertIn('app.dataset.mobileWorkspace = workspace', APP_JS)

    def test_mobile_target_control_opens_the_robot_workspace(self):
        target = re.search(r'<button class="target-banner".*?</button>', INDEX, re.S).group(0)
        self.assertIn('onclick="openRobotWorkspace()"', target)
        self.assertIn('aria-label="Choose which robots to control"', target)
        self.assertIn('setMobileWorkspace("robots")', self._function_body("openRobotWorkspace"))

    def test_compact_layout_supports_portrait_and_short_landscape_windows(self):
        media = "(max-width: 768px), (max-width: 960px) and (max-height: 600px)"
        self.assertIn(media, STYLE)
        self.assertIn(media, self._function_body("isCompactLayout"))
        self.assertIn("orientation: landscape", STYLE)
        self.assertIn("--mobile-rail-width", STYLE)

    def test_safe_area_is_shared_between_android_and_css(self):
        self.assertIn("viewport-fit=cover", INDEX)
        for side in ("top", "right", "bottom", "left"):
            self.assertIn(f"--android-safe-{side}", STYLE)
            self.assertIn(f"--android-safe-{side}", ANDROID_ACTIVITY)
        self.assertIn("WindowInsets.Type.systemBars()", ANDROID_ACTIVITY)
        self.assertIn("WindowInsets.Type.displayCutout()", ANDROID_ACTIVITY)
        self.assertIn("setOnApplyWindowInsetsListener", ANDROID_ACTIVITY)

    def test_mobile_touch_controls_do_not_depend_on_hover(self):
        self.assertRegex(
            STYLE,
            r"\.custom-gesture-delete\s*\{[^}]*width:\s*36px[^}]*opacity:\s*1",
        )
        self.assertRegex(
            STYLE,
            r"\.robot-menu-btn\s*\{[^}]*width:\s*48px[^}]*height:\s*48px[^}]*opacity:\s*1",
        )
        self.assertIn("prefers-reduced-motion: reduce", STYLE)


if __name__ == "__main__":
    unittest.main()
