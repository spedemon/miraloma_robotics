"""
nav_runtime.py — Navigation Runtime for LLM-Generated Code

This module provides the API that LLM-generated navigation scripts use.
Generated code imports functions from here and calls them to control the robot.

The module maintains a shared reference to the RobotHAL instance and a
`running` flag that continuous navigation loops should check.
"""

import time as _time
from typing import Optional

from robot_hal import RobotHAL


# ── Shared State ──────────────────────────────────────────────────
# These are set by main.py before any generated code runs.

_robot: Optional[RobotHAL] = None
running: bool = False


def _set_robot(hal: RobotHAL) -> None:
    """Set the shared HAL instance (called by main.py on startup)."""
    global _robot
    _robot = hal


def _get_robot() -> RobotHAL:
    """Get the shared HAL, raising if not configured."""
    if _robot is None:
        raise RuntimeError("Navigation runtime not initialized — no robot HAL set")
    return _robot


# ── Public API (used by generated code) ───────────────────────────

def send(action: str, value: int = 0) -> None:
    """Send a command to the robot.

    Args:
        action: Command ID from the protocol (e.g., 'MFW', 'STP', 'RTL', 'ACT')
        value: Parameter value (speed, angle, action ID, etc.)

    Examples:
        send('MFW', 150)   # Move forward at speed 150
        send('STP')        # Stop
        send('RTL', 100)   # Rotate left at speed 100
        send('ULA', 90)    # Set servo (head/eyes) to 90 degrees (center)
        send('ACT', 7)     # Trigger dancing action (Spider)
    """
    _get_robot().send_command(action, value)


def read(sensor: str, param: int = 0) -> str:
    """Read a sensor value from the robot.

    Args:
        sensor: Sensor ID from the protocol (e.g., 'ULD', 'LTR')
        param: Optional parameter (e.g., which line tracker sensor)

    Returns:
        Raw string response from the robot.

    Examples:
        distance = float(read('ULD'))      # Read ultrasonic distance in cm
        line = int(read('LTR', 0))         # Read left line tracker
    """
    return _get_robot().read_sensor(sensor, param)


def stop() -> None:
    """Emergency stop — halt all motors immediately."""
    _get_robot().stop()


def wait(seconds: float) -> None:
    """Wait for the given number of seconds.

    This checks the `running` flag periodically so that
    emergency stops can interrupt long waits.

    Args:
        seconds: Time to wait in seconds.
    """
    end_time = _time.time() + seconds
    while _time.time() < end_time and running:
        _time.sleep(min(0.1, end_time - _time.time()))


def is_running() -> bool:
    """Check if the navigation script should keep running.

    Use this in continuous navigation loops:
        while is_running():
            # ... navigation logic ...
    """
    return running
