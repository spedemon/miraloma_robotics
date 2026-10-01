"""Copy PlatformIO application images and create Mira's release manifest."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "robot_arms" / "web_app" / "firmware"


def macro(config: Path, name: str, pattern: str) -> str:
    match = re.search(rf'#define\s+{name}\s+{pattern}', config.read_text())
    if not match:
        raise RuntimeError(f"No {name} found in {config}")
    return match.group(1)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elf_fingerprint(path: Path) -> str:
    """Read esp_app_desc_t's ELF SHA-256 from an ESP32-C3 app image."""
    image = path.read_bytes()
    if len(image) < 0xD0 or image[0] != 0xE9:
        raise RuntimeError(f"Not an ESP application image: {path}")
    if struct.unpack_from("<H", image, 12)[0] != 5:
        raise RuntimeError(f"Not an ESP32-C3 application image: {path}")
    if struct.unpack_from("<I", image, 0x20)[0] != 0xABCD5432:
        raise RuntimeError(f"Application description is missing: {path}")
    return image[0xB0:0xD0].hex()


def add(role: str, project: str) -> dict:
    project_dir = ROOT / "robot_arms" / project
    config = project_dir / "include" / "config.h"
    firmware_version = macro(config, "MIRA_FIRMWARE_VERSION", r'"([^"]+)"')
    protocol_version = int(macro(config, "MIRA_PROTOCOL_VERSION", r'(\d+)'))
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
        "protocol": protocol_version,
        "chip": "esp32c3",
        "offset": "0x10000",
        "asset": filename,
        "sha256": digest(destination),
        "size": destination.stat().st_size,
        "elf_sha256": elf_fingerprint(destination),
        "provisioning_offset": "0x0",
        "provisioning_asset": factory_filename,
        "provisioning_sha256": digest(factory_destination),
        "provisioning_size": factory_destination.stat().st_size,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    old_manifest = {}
    try:
        old_manifest = json.loads((OUTPUT / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    for old in OUTPUT.glob("*.bin"):
        old.unlink()
    robot = add("robot", "robotarm_mcu")
    wireless = add("wireless_controller", "master_mcu")
    history = {
        image["elf_sha256"]: image
        for image in old_manifest.get("known_images", [])
        if image.get("elf_sha256") and image.get("role") and image.get("version")
    }
    for role, entry in (("robot", robot), ("wireless_controller", wireless)):
        history[entry["elf_sha256"]] = {
            "role": role,
            "version": entry["version"],
            "elf_sha256": entry["elf_sha256"],
        }
    manifest = {
        "schema": 2,
        "known_images": sorted(history.values(), key=lambda item: (item["role"], item["version"])),
        "robot": robot,
        "wireless_controller": wireless,
    }
    content = json.dumps(manifest, indent=2) + "\n"
    (OUTPUT / "manifest.json").write_text(content, encoding="utf-8")
    (OUTPUT / "mira-firmware-manifest.json").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
