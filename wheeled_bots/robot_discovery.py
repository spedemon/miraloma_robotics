"""
robot_discovery.py — Robot Discovery & Configuration

Scans the robots_firmware/ directory for available robots, loads their
protocol YAML files, firmware source code, and architecture descriptions.
Also builds and sets the Gemini system prompt for the selected robot.
"""

import yaml
from pathlib import Path

from gemini_client import GeminiClient


# ── Robot firmware platforms ──────────────────────────────────────

PLATFORM_INFO = {
    "microbit": {
        "label": "Micro:bit MakeCode (STS)",
        "icon": "📟",
        "copy_instructions": "Copy this code into MakeCode (makecode.microbit.org) and flash your Micro:bit V2.",
        "open_label": "🔗 Open MakeCode",
        "open_url": "https://makecode.microbit.org/",
        "language": "typescript",
    },
    "acecode": {
        "label": "ACECode (Arduino IDE)",
        "icon": "🕷️",
        "copy_instructions": "Open this code in Arduino IDE with the ACB_Spider_ESP8266 library installed, select your board, and flash via USB.",
        "open_label": "🔗 Open Arduino IDE",
        "open_url": "https://www.arduino.cc/en/software",
        "language": "c",
    },
}


# ── Discovery & Loading ──────────────────────────────────────────

def discover_robots(robots_dir: Path) -> list[str]:
    """Scan robots_firmware/ for subdirectories that contain a protocol.yaml."""
    robots = []
    if robots_dir.is_dir():
        for child in sorted(robots_dir.iterdir()):
            if child.is_dir() and (child / "protocol.yaml").exists():
                robots.append(child.name)
    return robots


def load_robot_config(robots_dir: Path, robot_name: str) -> dict:
    """Load and return the protocol.yaml for the given robot."""
    path = robots_dir / robot_name / "protocol.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f)
    return {}


def load_robot_firmware(robots_dir: Path, robot_name: str) -> tuple[str, str]:
    """Load the main firmware source file for the given robot.

    Returns (source_code, filename).
    Looks for common firmware file extensions.
    """
    robot_dir = robots_dir / robot_name
    for ext in (".ts", ".c", ".cpp", ".ino", ".py"):
        for fpath in robot_dir.glob(f"*{ext}"):
            if fpath.name.startswith("protocol"):
                continue
            return fpath.read_text(), fpath.name
    return "// No firmware source file found.", "unknown"


def load_robot_architecture(robots_dir: Path, robot_name: str) -> str:
    """Load the robot_architecture.md file for context."""
    path = robots_dir / robot_name / "robot_architecture.md"
    if path.exists():
        return path.read_text()
    return f"Robot: {robot_name}. No detailed architecture available."


def build_and_set_prompt(
    robots_dir: Path,
    robot_name: str,
    gemini: GeminiClient,
    robot_hal,
    calibration: dict,
    nav_runtime_module,
) -> None:
    """Build and set the system prompt for the selected robot.

    Also loads the protocol into the HAL and updates the nav_runtime
    so the 'robot' proxy object gets its methods.
    """
    config = load_robot_config(robots_dir, robot_name)
    architecture = load_robot_architecture(robots_dir, robot_name)
    prompt = GeminiClient.build_system_prompt(
        robot_name=config.get("name", robot_name.capitalize()),
        architecture_md=architecture,
        protocol_yaml=config,
        calibration=calibration,
    )
    gemini.set_system_prompt(prompt)

    # Also load protocol into HAL
    protocol_path = robots_dir / robot_name / "protocol.yaml"
    if protocol_path.exists():
        robot_hal.load_protocol(protocol_path)
        # Notify the runtime so the 'robot' proxy object gets its methods
        nav_runtime_module._set_robot(robot_hal)
