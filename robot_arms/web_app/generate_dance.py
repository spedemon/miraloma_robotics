#!/usr/bin/env python3
"""
generate_dance.py — West Coast Swing Dance Choreographer for Mira Robot Arm

Harvests positions from all existing gesture source files, builds a position
library with FK-computed metrics and distance matrices, then composes a
rhythmic dance sequence inspired by West Coast Swing patterns.

Outputs:
  - position_library.json  — full catalog of positions with metrics
  - west_coast_swing_dance.json — sequencer-compatible dance sequence

Usage:
  python3 generate_dance.py
"""

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from typing import List, Tuple, Optional, Dict
import random

# ============================================================================
# Arm geometry & kinematics (mirrored from config.h / ArmController.cpp)
# ============================================================================

ARM_BASE_HEIGHT  = 22.0   # d0: base pivot → shoulder pivot (mm)
ARM_LINK1_LENGTH = 40.0   # L1: shoulder → elbow (mm)
ARM_LINK2_LENGTH = 86.0   # L2: elbow → end effector (mm)

SERVO_BASE_OFFSET       = 0.0
SERVO_BASE_DIRECTION    = 1.0
SERVO_SHOULDER_OFFSET   = 90.0
SERVO_SHOULDER_DIRECTION = -1.0
SERVO_ELBOW_OFFSET      = 0.0
SERVO_ELBOW_DIRECTION   = -1.0

# Joint limits (servo degrees)
JOINT_BASE_MIN     = -90.0
JOINT_BASE_MAX     =  90.0
JOINT_SHOULDER_MIN = -109.0
JOINT_SHOULDER_MAX =  104.0
JOINT_ELBOW_MIN    = -100.0
JOINT_ELBOW_MAX    =  100.0
GRIP_OPEN_ANGLE    = -30.0
GRIP_CLOSED_ANGLE  =  45.0

# Home position (servo degrees)
HOME_BASE     = 0.0
HOME_SHOULDER = 0.0
HOME_ELBOW    = 0.0
HOME_GRIP     = GRIP_CLOSED_ANGLE

DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi


def forward_kinematics(base_deg: float, shoulder_deg: float, elbow_deg: float) -> Tuple[float, float, float]:
    """Servo angles (degrees) → Cartesian (x, y, z) in mm. Mirrors ArmController::forwardKinematics."""
    L1, L2, d0 = ARM_LINK1_LENGTH, ARM_LINK2_LENGTH, ARM_BASE_HEIGHT

    base_geo     = ((base_deg - SERVO_BASE_OFFSET) / SERVO_BASE_DIRECTION) * DEG2RAD
    shoulder_geo = ((shoulder_deg - SERVO_SHOULDER_OFFSET) / SERVO_SHOULDER_DIRECTION) * DEG2RAD
    elbow_geo    = ((elbow_deg - SERVO_ELBOW_OFFSET) / SERVO_ELBOW_DIRECTION) * DEG2RAD

    r    = L1 * math.cos(shoulder_geo) + L2 * math.cos(shoulder_geo + elbow_geo)
    zEff = L1 * math.sin(shoulder_geo) + L2 * math.sin(shoulder_geo + elbow_geo)

    x = r * math.cos(base_geo)
    y = r * math.sin(base_geo)
    z = zEff + d0

    return (x, y, z)


def cartesian_distance(p1: Tuple[float, float, float], p2: Tuple[float, float, float]) -> float:
    """Euclidean distance between two 3D points."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))


def joint_distance(a: 'Position', b: 'Position') -> float:
    """L2 norm of joint angle differences (degrees)."""
    return math.sqrt(
        (a.base - b.base) ** 2 +
        (a.shoulder - b.shoulder) ** 2 +
        (a.elbow - b.elbow) ** 2
    )


def classify_quadrant(x: float, y: float, z: float) -> str:
    """Classify a Cartesian position into a named region."""
    fb = "front" if x >= 60 else "back"
    lr = "left" if y > 5 else ("right" if y < -5 else "center")
    ud = "high" if z > 80 else ("low" if z < 40 else "mid")
    return f"{fb}-{lr}-{ud}"


def clamp_to_limits(base, shoulder, elbow, grip):
    """Clamp all joints to safe limits."""
    base     = max(JOINT_BASE_MIN, min(JOINT_BASE_MAX, base))
    shoulder = max(JOINT_SHOULDER_MIN, min(JOINT_SHOULDER_MAX, shoulder))
    elbow    = max(JOINT_ELBOW_MIN, min(JOINT_ELBOW_MAX, elbow))
    grip     = max(GRIP_OPEN_ANGLE, min(GRIP_CLOSED_ANGLE, grip))
    return base, shoulder, elbow, grip


# ============================================================================
# Position data structure
# ============================================================================

@dataclass
class Position:
    """A joint-space position with computed metadata."""
    base: float
    shoulder: float
    elbow: float
    grip: float
    source: str           # which gesture it came from
    index: int            # index within that gesture
    # Computed fields
    tooltip_x: float = 0.0
    tooltip_y: float = 0.0
    tooltip_z: float = 0.0
    quadrant: str = ""
    dist_from_home_cart: float = 0.0
    dist_from_home_joint: float = 0.0
    label: str = ""

    def compute_metadata(self, home_pos: Tuple[float, float, float]):
        self.tooltip_x, self.tooltip_y, self.tooltip_z = forward_kinematics(
            self.base, self.shoulder, self.elbow
        )
        self.quadrant = classify_quadrant(self.tooltip_x, self.tooltip_y, self.tooltip_z)
        self.dist_from_home_cart = cartesian_distance(
            (self.tooltip_x, self.tooltip_y, self.tooltip_z), home_pos
        )
        home_position = Position(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, HOME_GRIP, "home", 0)
        self.dist_from_home_joint = joint_distance(self, home_position)
        self.label = f"{self.source}_{self.index}"


# ============================================================================
# Phase 1: Parse keyframes from gesture .cpp files
# ============================================================================

GESTURE_DIR = os.path.join(os.path.dirname(__file__),
                           "..", "robotarm_mcu", "lib", "Gesture")


def parse_keyframe_array(filepath: str, source_name: str) -> List[Position]:
    """
    Parse a C++ keyframe array from a gesture .cpp file.
    Looks for lines like: { 0.0f, -16.0f, 78.0f, -25.0f, 1000 },
    Returns Position objects (without computed metadata yet).
    """
    positions = []
    with open(filepath, 'r') as f:
        content = f.read()

    # Match lines with 4 float values + 1 integer (duration)
    # Pattern: { float, float, float, float, int }
    pattern = r'\{\s*(-?[\d.]+)f?\s*,\s*(-?[\d.]+)f?\s*,\s*(-?[\d.]+)f?\s*,\s*(-?[\d.]+)f?\s*,\s*(\d+)\s*\}'
    matches = re.findall(pattern, content)

    for i, m in enumerate(matches):
        base, shoulder, elbow, grip = float(m[0]), float(m[1]), float(m[2]), float(m[3])
        positions.append(Position(
            base=base, shoulder=shoulder, elbow=elbow, grip=grip,
            source=source_name, index=i
        ))

    return positions


def sample_circle_positions(n: int = 12) -> List[Position]:
    """
    Sample positions from a parametric circle (side-view, XZ plane).
    Circle: center (64, 108), R=16mm. Y=0.
    We solve IK to get joint angles... but since we have FK only, let's
    sample by sweeping shoulder/elbow angles that trace the circle.
    Instead: use the known circle params and the JS IK to get angles.
    """
    # Circle in XZ plane: CX=64, CZ=108, CR=16
    # We'll approximate by computing FK for various shoulder/elbow combos
    # that land near the circle. Actually, let's just synthesize positions
    # by sweeping angles that create interesting arm poses.
    positions = []

    # Sample parametrically: shoulder sweeps -30..+30, elbow sweeps 30..80
    for i in range(n):
        t = i / n * 2 * math.pi
        # Create a circular sweep in joint space
        shoulder = 15.0 * math.sin(t)       # ±15°
        elbow    = 55.0 + 25.0 * math.cos(t) # 30..80°
        base     = 10.0 * math.sin(t * 0.5)  # gentle base sway
        grip     = 0.0

        positions.append(Position(
            base=base, shoulder=shoulder, elbow=elbow, grip=grip,
            source="circle_sampled", index=i
        ))

    return positions


def sample_front_circle_positions(n: int = 12) -> List[Position]:
    """
    Sample positions inspired by the front-facing circle.
    FCircle: X=90, center (Y=-2, Z=58), R=44mm.
    Translate to joint-space sweeps that create front-facing circular motion.
    """
    positions = []
    for i in range(n):
        t = i / n * 2 * math.pi
        # Front circle = mainly base (for Y) + shoulder/elbow (for Z)
        base     = 30.0 * math.sin(t)        # ±30° for wide Y sweep
        shoulder = -10.0 + 20.0 * math.cos(t) # oscillate shoulder
        elbow    = 40.0 + 30.0 * math.sin(t)  # oscillate elbow
        grip     = 0.0

        positions.append(Position(
            base=base, shoulder=shoulder, elbow=elbow, grip=grip,
            source="fcircle_sampled", index=i
        ))

    return positions


def sample_wave_positions(n: int = 16) -> List[Position]:
    """
    Sample positions from the Wave gesture's sinusoidal motion.
    Shoulder and elbow oscillate with 90° phase offset; base sweeps slowly.
    """
    positions = []
    SHOULDER_AMP = 12.0
    ELBOW_AMP = 18.0
    BASE_AMP = 80.0

    for i in range(n):
        t = i / n * 2 * math.pi
        base     = BASE_AMP * math.sin(t * 0.1)   # slow sweep
        shoulder = SHOULDER_AMP * math.sin(t)
        elbow    = ELBOW_AMP * math.sin(t + math.pi / 2)
        grip     = 0.0

        positions.append(Position(
            base=base, shoulder=shoulder, elbow=elbow, grip=grip,
            source="wave_sampled", index=i
        ))

    # Also sample wave positions with larger amplitudes (as suggested)
    for i in range(n):
        t = i / n * 2 * math.pi
        base     = BASE_AMP * 0.5 * math.sin(t * 0.15)
        shoulder = SHOULDER_AMP * 2.0 * math.sin(t)    # 2x amplitude
        elbow    = ELBOW_AMP * 2.0 * math.sin(t + math.pi / 2)
        grip     = 0.0

        positions.append(Position(
            base=base, shoulder=shoulder, elbow=elbow, grip=grip,
            source="wave_large_sampled", index=i
        ))

    return positions


def sample_square_corners() -> List[Position]:
    """
    Sample the square gesture corners. These are in Cartesian space, so we
    approximate with joint angles that produce similar reaches.
    """
    # Square: side-view XZ plane, corners at roughly ±11mm from center (64, 108)
    # We'll use varied shoulder/elbow combos
    positions = [
        Position(base=0, shoulder=-25, elbow=80, grip=0, source="square", index=0),  # top-right
        Position(base=0, shoulder=-25, elbow=50, grip=0, source="square", index=1),  # top-left
        Position(base=0, shoulder=10,  elbow=50, grip=0, source="square", index=2),  # bottom-left
        Position(base=0, shoulder=10,  elbow=80, grip=0, source="square", index=3),  # bottom-right
    ]
    return positions


def sample_fsquare_corners() -> List[Position]:
    """
    Front-facing square corners. Wide Y and Z range via base + arm angles.
    """
    positions = [
        Position(base=25,  shoulder=-15, elbow=50, grip=0, source="fsquare", index=0),
        Position(base=-25, shoulder=-15, elbow=50, grip=0, source="fsquare", index=1),
        Position(base=-25, shoulder=25,  elbow=30, grip=0, source="fsquare", index=2),
        Position(base=25,  shoulder=25,  elbow=30, grip=0, source="fsquare", index=3),
    ]
    return positions


def build_position_library() -> List[Position]:
    """Harvest positions from all gesture sources and compute metadata."""
    home_pos = forward_kinematics(HOME_BASE, HOME_SHOULDER, HOME_ELBOW)
    print(f"Home position (FK): x={home_pos[0]:.1f}, y={home_pos[1]:.1f}, z={home_pos[2]:.1f}")

    all_positions: List[Position] = []

    # Home position itself
    home = Position(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, HOME_GRIP, "home", 0)
    all_positions.append(home)

    # Parse keyframe-based gestures
    keyframe_gestures = {
        "dance": "DanceGesture.cpp",
        "break": "BreakGesture.cpp",
    }

    for name, filename in keyframe_gestures.items():
        filepath = os.path.join(GESTURE_DIR, filename)
        if os.path.exists(filepath):
            positions = parse_keyframe_array(filepath, name)
            all_positions.extend(positions)
            print(f"  Parsed {len(positions)} keyframes from {filename}")
        else:
            print(f"  WARNING: {filepath} not found")

    # Parse the crab gesture phases (they're not in a simple array, add manually)
    crab_positions = [
        Position(base=10, shoulder=0, elbow=116, grip=GRIP_OPEN_ANGLE, source="crab", index=0),    # retracted
        Position(base=0,  shoulder=0, elbow=68,  grip=GRIP_CLOSED_ANGLE, source="crab", index=1),   # lunge center
        Position(base=60, shoulder=0, elbow=68,  grip=GRIP_CLOSED_ANGLE, source="crab", index=2),   # lunge right
        Position(base=-60,shoulder=0, elbow=68,  grip=GRIP_CLOSED_ANGLE, source="crab", index=3),   # lunge left
    ]
    all_positions.extend(crab_positions)
    print(f"  Added {len(crab_positions)} crab positions")

    # Sample parametric gestures
    circle_pos = sample_circle_positions(12)
    all_positions.extend(circle_pos)
    print(f"  Sampled {len(circle_pos)} circle positions")

    fcircle_pos = sample_front_circle_positions(12)
    all_positions.extend(fcircle_pos)
    print(f"  Sampled {len(fcircle_pos)} front-circle positions")

    wave_pos = sample_wave_positions(16)
    all_positions.extend(wave_pos)
    print(f"  Sampled {len(wave_pos)} wave positions")

    square_pos = sample_square_corners()
    all_positions.extend(square_pos)
    print(f"  Added {len(square_pos)} square corners")

    fsquare_pos = sample_fsquare_corners()
    all_positions.extend(fsquare_pos)
    print(f"  Added {len(fsquare_pos)} front-square corners")

    # Compute metadata for all positions
    for p in all_positions:
        p.compute_metadata(home_pos)

    print(f"\nTotal positions in library: {len(all_positions)}")
    return all_positions


def build_distance_matrix(positions: List[Position]) -> Dict:
    """Build pairwise distance matrices (Cartesian and joint-space)."""
    n = len(positions)
    cart_matrix = [[0.0] * n for _ in range(n)]
    joint_matrix = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(i + 1, n):
            cd = cartesian_distance(
                (positions[i].tooltip_x, positions[i].tooltip_y, positions[i].tooltip_z),
                (positions[j].tooltip_x, positions[j].tooltip_y, positions[j].tooltip_z),
            )
            jd = joint_distance(positions[i], positions[j])
            cart_matrix[i][j] = round(cd, 2)
            cart_matrix[j][i] = round(cd, 2)
            joint_matrix[i][j] = round(jd, 2)
            joint_matrix[j][i] = round(jd, 2)

    return {
        "cartesian": cart_matrix,
        "joint_space": joint_matrix,
    }


# ============================================================================
# Phase 2: West Coast Swing Composition
# ============================================================================

# WCS rhythm patterns at ~120 BPM (beat = 500ms)
# Each pattern defines a sequence of (beat_fraction, move_type) pairs
# move_type guides position selection

BEAT_MS = 500  # 120 BPM

@dataclass
class MoveSpec:
    """Specification for a single move within a WCS pattern."""
    duration_beats: float      # in beats
    amplitude: str             # "small", "medium", "large"
    direction: str             # "home", "out", "side", "arc", "any"
    grip_style: str            # "open", "closed", "neutral", "snap"
    accent: bool = False       # rhythmic accent (sharper timing)


# WCS Pattern definitions
# Each pattern is a list of MoveSpecs forming one "phrase"

def pattern_anchor_step() -> List[MoveSpec]:
    """2-beat anchor: small settle near home. The 'grounding' move."""
    return [
        MoveSpec(1.0, "small", "home", "neutral"),
        MoveSpec(0.5, "small", "side", "neutral"),
        MoveSpec(0.5, "small", "home", "closed"),
    ]


def pattern_triple_step() -> List[MoveSpec]:
    """Triple step: quick-quick-slow (1+1+2 beats). Flowing arc movement."""
    return [
        MoveSpec(0.75, "medium", "side", "open"),
        MoveSpec(0.75, "medium", "arc", "neutral"),
        MoveSpec(1.5,  "medium", "any", "closed"),
    ]


def pattern_sugar_push() -> List[MoveSpec]:
    """Sugar push: 6 beats. Push out + settle + pull back."""
    return [
        MoveSpec(1.0, "medium", "out", "open"),       # reach out
        MoveSpec(1.0, "large",  "out", "open"),        # extend further
        MoveSpec(1.0, "medium", "any", "snap"),        # catch (accent)
        MoveSpec(1.0, "small",  "home", "closed"),     # pull back
        MoveSpec(1.0, "small",  "side", "neutral"),    # settle
        MoveSpec(1.0, "small",  "home", "closed"),     # anchor
    ]


def pattern_side_pass() -> List[MoveSpec]:
    """Side pass: 6 beats. Lateral sweep from one side to the other."""
    return [
        MoveSpec(1.0, "medium", "side", "open"),       # step out
        MoveSpec(1.5, "large",  "side", "neutral"),    # sweep across
        MoveSpec(1.5, "medium", "arc", "neutral"),     # arc through
        MoveSpec(1.0, "small",  "side", "closed"),     # settle
        MoveSpec(1.0, "small",  "home", "closed"),     # anchor
    ]


def pattern_whip() -> List[MoveSpec]:
    """Whip: 8 beats. Circular sweep with direction change. Most dramatic."""
    return [
        MoveSpec(1.0, "medium", "out", "open"),        # setup
        MoveSpec(1.0, "large",  "arc", "open"),        # sweep out
        MoveSpec(1.0, "large",  "arc", "neutral"),     # top of arc
        MoveSpec(1.0, "large",  "side", "snap"),       # direction change!
        MoveSpec(1.0, "medium", "arc", "neutral"),     # swing back
        MoveSpec(1.0, "medium", "any", "neutral"),     # continue
        MoveSpec(1.0, "small",  "side", "closed"),     # decelerate
        MoveSpec(1.0, "small",  "home", "closed"),     # anchor
    ]


def pattern_sway() -> List[MoveSpec]:
    """Simple sway: 4 beats. Gentle side-to-side."""
    return [
        MoveSpec(1.0, "small", "side", "neutral"),
        MoveSpec(1.0, "small", "side", "neutral"),
        MoveSpec(1.0, "small", "side", "neutral"),
        MoveSpec(1.0, "small", "home", "closed"),
    ]


def pattern_body_roll() -> List[MoveSpec]:
    """Body roll: 4 beats. Shoulder-then-elbow wave-like motion."""
    return [
        MoveSpec(1.0, "medium", "out", "open"),
        MoveSpec(0.75, "medium", "arc", "neutral"),
        MoveSpec(0.75, "medium", "arc", "neutral"),
        MoveSpec(1.5,  "small",  "home", "closed"),
    ]


# Amplitude scale factors for "gentle" dance
# These are higher than a conservative approach — we want visible movement,
# but still gentle and flowing (not explosive like breakdance)
AMPLITUDE_SCALES = {
    "small":  0.35,
    "medium": 0.55,
    "large":  0.75,
}


class WCSDanceComposer:
    """Composes a West Coast Swing dance from the position library."""

    def __init__(self, positions: List[Position], seed: int = 42):
        self.positions = positions
        self.rng = random.Random(seed)
        self.home_pos = forward_kinematics(HOME_BASE, HOME_SHOULDER, HOME_ELBOW)
        self._recently_used: List[int] = []  # track indices to avoid repetition
        self._max_recent = 12  # how many recent positions to avoid

        # Classify positions by properties for selection
        self._classify_positions()

    def _classify_positions(self):
        """Group positions by useful properties for pattern-based selection."""
        self.by_quadrant: Dict[str, List[Position]] = {}
        self.by_source: Dict[str, List[Position]] = {}
        self.by_amplitude: Dict[str, List[Position]] = {
            "small": [], "medium": [], "large": []
        }

        for p in self.positions:
            # By quadrant
            self.by_quadrant.setdefault(p.quadrant, []).append(p)
            # By source
            self.by_source.setdefault(p.source, []).append(p)
            # By amplitude (distance from home)
            if p.dist_from_home_joint < 40:
                self.by_amplitude["small"].append(p)
            elif p.dist_from_home_joint < 100:
                self.by_amplitude["medium"].append(p)
            else:
                self.by_amplitude["large"].append(p)

        print(f"\nPosition classification:")
        print(f"  Small (near home):  {len(self.by_amplitude['small'])} positions")
        print(f"  Medium:             {len(self.by_amplitude['medium'])} positions")
        print(f"  Large (far):        {len(self.by_amplitude['large'])} positions")
        print(f"  Quadrants:          {list(self.by_quadrant.keys())}")

    def _select_position(self, spec: MoveSpec, prev_pos: Optional[Position],
                         side_bias: float = 0.0) -> Position:
        """
        Select a position matching a MoveSpec, with smooth flow from prev_pos.
        Avoids recently-used positions for variety.

        Args:
            spec: The move specification to match
            prev_pos: Previous position for continuity
            side_bias: -1.0 = prefer left, +1.0 = prefer right, 0 = any
        """
        candidates = list(self.by_amplitude.get(spec.amplitude, self.positions))

        # Fallback if we have no candidates in the desired amplitude
        if not candidates:
            candidates = list(self.positions)

        # Filter out recently-used positions (by index in self.positions)
        if len(candidates) > self._max_recent + 3:
            recent_set = set(self._recently_used)
            fresh = [p for p in candidates
                     if self.positions.index(p) not in recent_set]
            if len(fresh) >= 3:
                candidates = fresh

        # Direction filtering
        if spec.direction == "home":
            # Prefer positions close to home, but not identical to home
            candidates.sort(key=lambda p: p.dist_from_home_joint)
            # Skip exact home (index 0), take near-home positions
            near_home = [p for p in candidates if 5 < p.dist_from_home_joint < 50]
            if near_home:
                candidates = near_home[:max(5, len(near_home) // 3)]
            else:
                candidates = candidates[:max(5, len(candidates) // 4)]
        elif spec.direction == "out":
            # Prefer positions far from home (forward reach)
            candidates.sort(key=lambda p: -p.dist_from_home_joint)
            candidates = candidates[:max(5, len(candidates) // 3)]
        elif spec.direction == "side":
            # Prefer positions with base rotation (lateral movement)
            if side_bias != 0:
                if side_bias > 0:
                    candidates = [p for p in candidates if p.base > 5] or candidates
                else:
                    candidates = [p for p in candidates if p.base < -5] or candidates
            else:
                candidates = [p for p in candidates if abs(p.base) > 8] or candidates
        elif spec.direction == "arc":
            # Prefer positions from circle/wave sources for flowing arcs
            arc_sources = {"circle_sampled", "fcircle_sampled", "wave_sampled",
                           "wave_large_sampled"}
            arc_candidates = [p for p in candidates if p.source in arc_sources]
            if arc_candidates:
                candidates = arc_candidates

        # If we have a previous position, prefer positions that are
        # at a moderate distance (not too close = boring, not too far = jerky)
        if prev_pos and len(candidates) > 3:
            def flow_score(p: Position) -> float:
                jd = joint_distance(p, prev_pos)
                # Ideal joint distance depends on amplitude
                ideal = {"small": 25, "medium": 55, "large": 85}.get(spec.amplitude, 45)
                return abs(jd - ideal) + self.rng.random() * 20  # add randomness
            candidates.sort(key=flow_score)
            candidates = candidates[:max(3, len(candidates) // 3)]

        chosen = self.rng.choice(candidates)

        # Track recently-used
        idx = self.positions.index(chosen)
        self._recently_used.append(idx)
        if len(self._recently_used) > self._max_recent:
            self._recently_used.pop(0)

        return chosen

    def _interpolate_position(self, pos_a: Position, pos_b: Position,
                              t: float) -> Position:
        """
        Create a new position by interpolating between two library positions.
        This generates unique in-between poses for smoother flow.
        t=0 → pos_a, t=1 → pos_b
        """
        return Position(
            base=pos_a.base + (pos_b.base - pos_a.base) * t,
            shoulder=pos_a.shoulder + (pos_b.shoulder - pos_a.shoulder) * t,
            elbow=pos_a.elbow + (pos_b.elbow - pos_a.elbow) * t,
            grip=pos_a.grip + (pos_b.grip - pos_a.grip) * t,
            source="interpolated",
            index=0,
        )

    def _compute_grip(self, spec: MoveSpec, beat_in_phrase: float,
                      position: Position, phrase_index: int = 0) -> float:
        """Compute grip angle based on the move's grip style with variety."""
        if spec.grip_style == "open":
            # Vary the open amount slightly per phrase
            openness = 0.6 + 0.2 * math.sin(phrase_index * 1.3)
            return GRIP_OPEN_ANGLE * openness
        elif spec.grip_style == "closed":
            closedness = 0.7 + 0.2 * math.sin(phrase_index * 0.7)
            return GRIP_CLOSED_ANGLE * closedness
        elif spec.grip_style == "snap":
            return GRIP_CLOSED_ANGLE  # full snap
        else:  # "neutral"
            # Multi-frequency sinusoidal for organic feel
            phase = beat_in_phrase * math.pi * 2
            return (10.0 * math.sin(phase) +
                    5.0 * math.sin(phase * 2.3 + phrase_index))

    def _scale_position(self, pos: Position, scale: float) -> Tuple[float, float, float, float]:
        """Scale a position's angles by blending toward home."""
        base     = HOME_BASE     + (pos.base - HOME_BASE) * scale
        shoulder = HOME_SHOULDER + (pos.shoulder - HOME_SHOULDER) * scale
        elbow    = HOME_ELBOW    + (pos.elbow - HOME_ELBOW) * scale
        grip     = pos.grip
        return clamp_to_limits(base, shoulder, elbow, grip)

    def compose(self) -> List[dict]:
        """
        Compose the full WCS dance sequence.
        Returns a list of keyframe dicts ready for JSON export.
        """
        # Define the song structure: sequence of patterns
        # A typical WCS "song" cycles through these patterns
        song_structure = [
            # Intro: gentle entry
            ("anchor",     pattern_anchor_step),
            ("sway",       pattern_sway),
            # Verse 1: building energy
            ("triple",     pattern_triple_step),
            ("sugar_push", pattern_sugar_push),
            ("anchor",     pattern_anchor_step),
            # Verse 2: more movement
            ("side_pass",  pattern_side_pass),
            ("body_roll",  pattern_body_roll),
            ("triple",     pattern_triple_step),
            ("anchor",     pattern_anchor_step),
            # Bridge: peak energy
            ("whip",       pattern_whip),
            ("triple",     pattern_triple_step),
            ("sugar_push", pattern_sugar_push),
            # Verse 3: varied
            ("sway",       pattern_sway),
            ("side_pass",  pattern_side_pass),
            ("body_roll",  pattern_body_roll),
            ("anchor",     pattern_anchor_step),
            # Outro: wind down
            ("whip",       pattern_whip),
            ("triple",     pattern_triple_step),
            ("sway",       pattern_sway),
            ("anchor",     pattern_anchor_step),
        ]

        keyframes = []
        prev_pos = None
        total_beats = 0
        side_direction = 1.0  # alternate sides
        prev_selected = None  # for interpolation

        # Start from home
        keyframes.append({
            "base": HOME_BASE,
            "shoulder": HOME_SHOULDER,
            "elbow": HOME_ELBOW,
            "grip": HOME_GRIP,
            "durationMs": int(BEAT_MS * 2),  # 2-beat intro hold
        })

        for phrase_idx, (pattern_name, pattern_fn) in enumerate(song_structure):
            moves = pattern_fn()
            beat_in_phrase = 0.0

            for move_idx, spec in enumerate(moves):
                # Select a position matching the spec
                pos = self._select_position(spec, prev_pos, side_bias=side_direction)

                # Optionally interpolate between prev and selected for smoother flow
                if prev_selected and self.rng.random() < 0.3 and spec.direction == "arc":
                    interp_t = 0.3 + self.rng.random() * 0.4  # 30-70%
                    pos = self._interpolate_position(prev_selected, pos, interp_t)

                # Scale amplitude for gentle dance feel
                scale = AMPLITUDE_SCALES[spec.amplitude]
                base, shoulder, elbow, grip = self._scale_position(pos, scale)

                # Override grip with rhythmic choreography
                grip_angle = self._compute_grip(
                    spec, beat_in_phrase / max(1, len(moves)), pos, phrase_idx
                )
                _, _, _, grip_angle = clamp_to_limits(0, 0, 0, grip_angle)

                # Compute duration from beats
                duration_ms = int(spec.duration_beats * BEAT_MS)
                if spec.accent:
                    duration_ms = int(duration_ms * 0.8)  # slightly faster for accents

                # Add subtle tempo variation (±8%) for human feel
                tempo_var = 1.0 + (self.rng.random() * 0.16 - 0.08)
                duration_ms = int(duration_ms * tempo_var)

                # Minimum duration guard
                duration_ms = max(200, duration_ms)

                keyframes.append({
                    "base": round(base, 1),
                    "shoulder": round(shoulder, 1),
                    "elbow": round(elbow, 1),
                    "grip": round(grip_angle, 1),
                    "durationMs": duration_ms,
                })

                prev_pos = pos
                prev_selected = pos
                beat_in_phrase += spec.duration_beats
                total_beats += spec.duration_beats

            # Alternate side direction between phrases
            side_direction *= -1

        # End with return to home
        keyframes.append({
            "base": HOME_BASE,
            "shoulder": HOME_SHOULDER,
            "elbow": HOME_ELBOW,
            "grip": HOME_GRIP,
            "durationMs": int(BEAT_MS * 2),
        })

        print(f"\nComposed {len(keyframes)} keyframes over {total_beats:.0f} beats "
              f"({total_beats * BEAT_MS / 1000:.1f}s)")

        return keyframes


# ============================================================================
# Phase 3: Validation
# ============================================================================

def validate_sequence(keyframes: List[dict]) -> bool:
    """Validate joint limits and smoothness of the sequence."""
    all_ok = True

    print("\n=== Sequence Validation ===")

    max_velocities = {"base": 0, "shoulder": 0, "elbow": 0, "grip": 0}

    for i in range(1, len(keyframes)):
        prev = keyframes[i - 1]
        curr = keyframes[i]

        # Check joint limits
        for joint, (lo, hi) in [
            ("base", (JOINT_BASE_MIN, JOINT_BASE_MAX)),
            ("shoulder", (JOINT_SHOULDER_MIN, JOINT_SHOULDER_MAX)),
            ("elbow", (JOINT_ELBOW_MIN, JOINT_ELBOW_MAX)),
            ("grip", (GRIP_OPEN_ANGLE, GRIP_CLOSED_ANGLE)),
        ]:
            val = curr[joint]
            if val < lo or val > hi:
                print(f"  ⚠ Keyframe {i}: {joint}={val:.1f}° outside [{lo}, {hi}]")
                all_ok = False

        # Compute angular velocity (deg/s)
        dt_s = curr["durationMs"] / 1000.0
        if dt_s > 0:
            for joint in ["base", "shoulder", "elbow", "grip"]:
                vel = abs(curr[joint] - prev[joint]) / dt_s
                max_velocities[joint] = max(max_velocities[joint], vel)
                if vel > 200:
                    print(f"  ⚠ Keyframe {i}: {joint} velocity = {vel:.0f}°/s (>200°/s)")

    # Compute FK for each keyframe to verify positions are reasonable
    for i, kf in enumerate(keyframes):
        x, y, z = forward_kinematics(kf["base"], kf["shoulder"], kf["elbow"])
        if z < 0:
            print(f"  ⚠ Keyframe {i}: tooltip below table (z={z:.1f}mm)")
            all_ok = False

    total_ms = sum(kf["durationMs"] for kf in keyframes)
    print(f"\n  Total keyframes:   {len(keyframes)}")
    print(f"  Total duration:    {total_ms / 1000:.1f}s")
    print(f"  Max velocities:")
    for joint, vel in max_velocities.items():
        status = "✓" if vel <= 200 else "⚠"
        print(f"    {status} {joint:>10s}: {vel:.0f}°/s")

    if all_ok:
        print("\n  ✓ All checks passed!")
    else:
        print("\n  ⚠ Some issues detected (see above)")

    return all_ok

def smooth_velocity_spikes(keyframes: List[dict], max_vel: float = 180.0) -> List[dict]:
    """
    Post-process keyframes to smooth out velocity spikes.
    If any joint would exceed max_vel (deg/s), extend the duration.
    Also optionally inserts an intermediate keyframe for very large jumps.
    """
    smoothed = [keyframes[0]]
    fixes = 0

    for i in range(1, len(keyframes)):
        prev = smoothed[-1]
        curr = dict(keyframes[i])  # copy

        # Compute max joint velocity
        dt_s = curr["durationMs"] / 1000.0
        if dt_s > 0:
            max_joint_vel = 0
            for joint in ["base", "shoulder", "elbow", "grip"]:
                vel = abs(curr[joint] - prev[joint]) / dt_s
                max_joint_vel = max(max_joint_vel, vel)

            if max_joint_vel > max_vel:
                # Option 1: Extend duration to bring velocity under limit
                needed_dt = 0
                for joint in ["base", "shoulder", "elbow", "grip"]:
                    delta = abs(curr[joint] - prev[joint])
                    if delta > 0:
                        needed_dt = max(needed_dt, delta / max_vel)
                new_duration = int(needed_dt * 1000) + 1
                # Don't extend more than 2x original
                new_duration = min(new_duration, curr["durationMs"] * 2)

                if max_joint_vel > max_vel * 1.5 and curr["durationMs"] >= 300:
                    # Option 2: For very large jumps, insert an intermediate keyframe
                    mid = {}
                    for joint in ["base", "shoulder", "elbow", "grip"]:
                        mid[joint] = round((prev[joint] + curr[joint]) / 2, 1)
                    mid["durationMs"] = max(200, curr["durationMs"] // 2)
                    curr["durationMs"] = max(200, curr["durationMs"] // 2)
                    smoothed.append(mid)
                    fixes += 1
                else:
                    curr["durationMs"] = max(curr["durationMs"], new_duration)
                    fixes += 1

        smoothed.append(curr)

    if fixes > 0:
        print(f"  Smoothed {fixes} velocity spikes (max allowed: {max_vel}°/s)")
    else:
        print(f"  No velocity spikes detected")

    return smoothed


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 60)
    print("  Mira WCS Dance Choreographer")
    print("=" * 60)

    # Phase 1: Build position library
    print("\n--- Phase 1: Building Position Library ---")
    positions = build_position_library()
    distance_matrices = build_distance_matrix(positions)

    # Save position library
    lib_data = {
        "created": datetime.now(timezone.utc).isoformat(),
        "position_count": len(positions),
        "positions": [asdict(p) for p in positions],
        "distance_matrix_cartesian": distance_matrices["cartesian"],
        "distance_matrix_joint_space": distance_matrices["joint_space"],
    }

    lib_path = os.path.join(os.path.dirname(__file__), "position_library.json")
    with open(lib_path, 'w') as f:
        json.dump(lib_data, f, indent=2)
    print(f"\nSaved position library to: {lib_path}")

    # Phase 2: Compose the dance
    print("\n--- Phase 2: Composing WCS Dance ---")
    composer = WCSDanceComposer(positions, seed=42)
    keyframes = composer.compose()

    # Phase 2b: Smooth velocity spikes
    print("\n--- Phase 2b: Smoothing Velocity Spikes ---")
    keyframes = smooth_velocity_spikes(keyframes, max_vel=180.0)

    # Phase 3: Validate
    print("\n--- Phase 3: Validation ---")
    validate_sequence(keyframes)

    # Save dance sequence
    dance_data = {
        "name": "West Coast Swing Dance",
        "created": datetime.now(timezone.utc).isoformat(),
        "totalDurationMs": sum(kf["durationMs"] for kf in keyframes),
        "keyframes": keyframes,
    }

    dance_path = os.path.join(os.path.dirname(__file__), "west_coast_swing_dance.json")
    with open(dance_path, 'w') as f:
        json.dump(dance_data, f, indent=2)
    print(f"\nSaved dance sequence to: {dance_path}")

    # Summary
    print("\n" + "=" * 60)
    print("  Done! You can load west_coast_swing_dance.json in the")
    print("  sequencer UI to preview and play on the robot.")
    print("=" * 60)


if __name__ == "__main__":
    main()
