"""Copy PlatformIO application images and create Mira's release manifest."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "robot_arms" / "web_app" / "firmware"


def version(config: Path) -> str:
    match = re.search(r'#define\s+MIRA_FIRMWARE_VERSION\s+"([^"]+)"', config.read_text())
    if not match:
        raise RuntimeError(f"No firmware version found in {config}")
    return match.group(1)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add(role: str, project: str) -> dict:
    project_dir = ROOT / "robot_arms" / project
    firmware_version = version(project_dir / "include" / "config.h")
    build_dir = project_dir / ".pio" / "build" / "esp32c3"
    source = build_dir / "firmware.bin"
    factory_source = build_dir / "firmware.factory.bin"
    for required in (source, factory_source):
        if not required.exists():
            raise RuntimeError(f"Build output is missing: {required}")
    filename = f"mira-{role.replace('_', '-')}-{firmware_version}.bin"
    factory_filename = f"mira-{role.replace('_', '-')}-{firmware_version}-factory.bin"
    destination = OUTPUT / filename
    factory_destination = OUTPUT / factory_filename
    shutil.copy2(source, destination)
    shutil.copy2(factory_source, factory_destination)
    return {
        "version": firmware_version,
        "protocol": 1,
        "chip": "esp32c3",
        "offset": "0x10000",
        "asset": filename,
        "sha256": digest(destination),
        "size": destination.stat().st_size,
        "provisioning_offset": "0x0",
        "provisioning_asset": factory_filename,
        "provisioning_sha256": digest(factory_destination),
        "provisioning_size": factory_destination.stat().st_size,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for old in OUTPUT.glob("*.bin"):
        old.unlink()
    manifest = {
        "schema": 1,
        "robot": add("robot", "robotarm_mcu"),
        "wireless_controller": add("wireless_controller", "master_mcu"),
    }
    content = json.dumps(manifest, indent=2) + "\n"
    (OUTPUT / "manifest.json").write_text(content, encoding="utf-8")
    (OUTPUT / "mira-firmware-manifest.json").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
