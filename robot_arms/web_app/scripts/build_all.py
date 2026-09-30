#!/usr/bin/env python3
"""Build Mira firmware and the desktop installer for the current platform.

The default command builds both firmware roles, creates the firmware manifest,
and then packages the native desktop application. CI uses the two partial modes
to build firmware once on Linux and package the app on macOS and Windows.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WEB_APP = ROOT / "robot_arms" / "web_app"
FIRMWARE_PROJECTS = (
    ROOT / "robot_arms" / "robotarm_mcu",
    ROOT / "robot_arms" / "master_mcu",
)
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def build_firmware() -> None:
    for project in FIRMWARE_PROJECTS:
        run([sys.executable, "-m", "platformio", "run", "-d", str(project)])
    run([sys.executable, str(WEB_APP / "scripts" / "build_firmware_manifest.py")])


def build_desktop(version: str, system: str | None = None) -> None:
    system = system or platform.system()
    env = os.environ.copy()
    env["MIRA_VERSION"] = version

    if system == "Darwin":
        run(["bash", str(WEB_APP / "scripts" / "build_macos.sh")], env=env)
        return
    if system == "Windows":
        powershell = (
            shutil.which("pwsh")
            or shutil.which("powershell")
            or shutil.which("powershell.exe")
        )
        if not powershell:
            raise RuntimeError("PowerShell is required to build the Windows installer.")
        run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(WEB_APP / "scripts" / "build_windows.ps1"),
            ],
            env=env,
        )
        return
    raise RuntimeError(
        "Desktop installers can only be built on their native platform. "
        "Use --firmware-only on Linux, or create a tag so GitHub Actions builds macOS and Windows."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--firmware-only",
        action="store_true",
        help="build both firmware roles and manifests",
    )
    mode.add_argument(
        "--app-only",
        action="store_true",
        help="package the app using firmware already in firmware/",
    )
    parser.add_argument(
        "--version",
        default=os.environ.get("MIRA_VERSION", "0.1.0"),
        help="desktop application version (default: MIRA_VERSION or 0.1.0)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not VERSION_PATTERN.fullmatch(args.version):
        raise SystemExit(f"Invalid version {args.version!r}; use a semantic version such as 0.2.0")

    if not args.app_only:
        build_firmware()
    if not args.firmware_only:
        build_desktop(args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
