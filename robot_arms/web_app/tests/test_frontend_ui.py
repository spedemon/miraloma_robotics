import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


WEB_APP_DIR = Path(__file__).resolve().parents[1]
INDEX = (WEB_APP_DIR / "static" / "index.html").read_text()
APP_JS = (WEB_APP_DIR / "static" / "app.js").read_text()
ICONS_PATH = WEB_APP_DIR / "static" / "icons.svg"


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

    def test_calibration_opens_only_after_requesting_home(self):
        body = self._function_body("openCalibration")
        self.assertLess(body.index("sendHome();"), body.index("revealCalibration();"))

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


if __name__ == "__main__":
    unittest.main()
