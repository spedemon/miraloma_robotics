import importlib.util
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_all.py"
SPEC = importlib.util.spec_from_file_location("build_all", SCRIPT)
build_all = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(build_all)


class BuildCoordinatorTests(unittest.TestCase):
    def test_firmware_builds_both_roles_before_manifest(self):
        with mock.patch.object(build_all, "run") as run:
            build_all.build_firmware()

        self.assertEqual(run.call_count, 3)
        projects = [call.args[0][-1] for call in run.call_args_list[:2]]
        self.assertEqual(
            projects,
            [
                str(build_all.ROOT / "robot_arms" / "robotarm_mcu"),
                str(build_all.ROOT / "robot_arms" / "master_mcu"),
            ],
        )
        self.assertTrue(run.call_args_list[2].args[0][-1].endswith("build_firmware_manifest.py"))

    def test_macos_build_receives_the_requested_version(self):
        with mock.patch.object(build_all, "run") as run:
            build_all.build_desktop("1.2.3", system="Darwin")

        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertEqual(command[0], "bash")
        self.assertTrue(command[-1].endswith("build_macos.sh"))
        self.assertEqual(environment["MIRA_VERSION"], "1.2.3")

    def test_windows_build_receives_the_requested_version(self):
        with mock.patch.object(build_all.shutil, "which", return_value="pwsh"), mock.patch.object(
            build_all, "run"
        ) as run:
            build_all.build_desktop("1.2.3", system="Windows")

        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertEqual(command[0], "pwsh")
        self.assertTrue(command[-1].endswith("build_windows.ps1"))
        self.assertEqual(environment["MIRA_VERSION"], "1.2.3")

    def test_linux_desktop_build_explains_native_packaging(self):
        with self.assertRaisesRegex(RuntimeError, "native platform"):
            build_all.build_desktop("1.2.3", system="Linux")


if __name__ == "__main__":
    unittest.main()
