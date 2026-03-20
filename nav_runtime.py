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


# ── Command Mappings ──────────────────────────────────────────────

# Mapping from protocol command ID to (method_name, param_name, default_value)
COMMAND_METHODS = {
    "STP": ("stop", None, 0),
    "MFW": ("move_forward", "speed", 0),
    "MBW": ("move_backward", "speed", 0),
    "MSL": ("strafe_left", "speed", 0),
    "MSR": ("strafe_right", "speed", 0),
    "RTL": ("rotate_left", "speed", 0),
    "RTR": ("rotate_right", "speed", 0),
    "WFL": ("set_wheel_front_left", "speed", 0),
    "WFR": ("set_wheel_front_right", "speed", 0),
    "WBL": ("set_wheel_back_left", "speed", 0),
    "WBR": ("set_wheel_back_right", "speed", 0),
    "ULA": ("set_head_angle", "angle", 90),
    "LDL": ("set_left_led", "state", 0),
    "DIC": ("clear_display", None, 0),
    "ACT": ("do_action", "action_id", 1),
}

# Mapping from protocol sensor ID to (method_name, param_name, default_value)
SENSOR_METHODS = {
    "ULD": ("read_distance", None, 0),
    "LTR": ("read_line_tracker", "sensor", 0),
}


class Robot:
    """Friendly proxy for the robot hardware.

    LLM-generated code uses this object: `robot.move_forward(150)`
    instead of `send('MFW', 150)`.
    """

    def __init__(self, hal_getter):
        self._get_hal = hal_getter

    def __getattr__(self, name: str):
        # This handles dynamically added methods that might not be in the static mapping
        # but exist in the protocol. We'll stick to the mapping for the official API though.
        raise AttributeError(f"'Robot' object has no attribute '{name}'")

    def stop(self) -> None:
        """Emergency stop — halt all motors immediately."""
        try:
            self._get_hal().stop()
        except ConnectionError:
            pass

    def wait(self, seconds: float) -> None:
        """Wait for the given number of seconds (interruptible)."""
        end_time = _time.time() + seconds
        while _time.time() < end_time and running:
            _time.sleep(min(0.1, end_time - _time.time()))

    def is_running(self) -> bool:
        """Check if the navigation script should keep running."""
        return running

    # ── Command Delegates ──────────────────────────────────────────

    def _send_cmd(self, action_id: str, value: int = 0):
        try:
            self._get_hal().send_command(action_id, value)
        except ConnectionError:
            pass

    def _read_sensor(self, sensor_id: str, value: int = 0) -> float:
        try:
            resp = self._get_hal().read_sensor(sensor_id, value)
            return float(resp)
        except (ValueError, ConnectionError):
            return -1.0

    @classmethod
    def _create_dynamic_methods(cls, setter_ids: list[str], getter_ids: list[str]):
        """Dynamically add methods to the class based on protocol IDs."""
        for cmd_id in setter_ids:
            if cmd_id in COMMAND_METHODS:
                method_name, param_name, _ = COMMAND_METHODS[cmd_id]

                # Create a closure for the method
                def make_method(cid, pname):
                    if pname:
                        return lambda self, val: self._send_cmd(cid, val)
                    else:
                        return lambda self: self._send_cmd(cid)

                setattr(cls, method_name, make_method(cmd_id, param_name))

        for sensor_id in getter_ids:
            if sensor_id in SENSOR_METHODS:
                method_name, param_name, _ = SENSOR_METHODS[sensor_id]

                # Create a closure for the method
                def make_method(sid, pname):
                    if pname:
                        return lambda self, val=0: self._read_sensor(sid, val)
                    else:
                        return lambda self: self._read_sensor(sid)

                setattr(cls, method_name, make_method(sensor_id, param_name))


# ── Shared State ──────────────────────────────────────────────────
# These are set by main.py before any generated code runs.

_robot_hal: Optional[RobotHAL] = None
running: bool = False

# The singleton robot instance used by generated code
robot: Robot = Robot(lambda: _get_robot())


def _set_robot(hal: RobotHAL) -> None:
    """Set the shared HAL instance and update the Robot object methods."""
    global _robot_hal
    _robot_hal = hal
    # Update Robot class with methods supported by this protocol
    Robot._create_dynamic_methods(hal.setter_ids, hal.getter_ids)


def _get_robot() -> RobotHAL:
    """Get the shared HAL, raising if not configured."""
    if _robot_hal is None:
        raise RuntimeError("Navigation runtime not initialized — no robot HAL set")
    return _robot_hal


# ── Public API (backward compatibility) ───────────────────────────

def send(action: str, value: int = 0) -> None:
    """[DEPRECATED] Use robot.methods instead. Send a command to the robot."""
    try:
        _get_robot().send_command(action, value)
    except ConnectionError:
        pass


def read(sensor: str, param: int = 0) -> str:
    """[DEPRECATED] Use robot.methods instead. Read a sensor value."""
    try:
        return _get_robot().read_sensor(sensor, param)
    except ConnectionError:
        return "0.0"


def stop() -> None:
    """[DEPRECATED] Use robot.stop() instead."""
    robot.stop()


def wait(seconds: float) -> None:
    """[DEPRECATED] Use robot.wait() instead."""
    robot.wait(seconds)


def is_running() -> bool:
    """[DEPRECATED] Use robot.is_running() instead. Check if script should keep running."""
    return robot.is_running()
