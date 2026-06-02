/**
 * config.h — Mira Motor MCU Configuration
 *
 * All hardware settings in one place.
 * Edit this file to match your wiring and servo specifications.
 */

#ifndef MIRA_CONFIG_H
#define MIRA_CONFIG_H

// ---------------------------------------------------------------------------
// I2C Bus
// ---------------------------------------------------------------------------
#define PIN_SDA 2
#define PIN_SCL 3

// ---------------------------------------------------------------------------
// PCA9685 PWM Driver
// ---------------------------------------------------------------------------
#define PCA9685_ADDR 0x40 // Default I2C address
#define PCA9685_FREQ 200 // PWM frequency in Hz (higher = smoother servo motion)

// ---------------------------------------------------------------------------
// Servo Channel Assignments (PCA9685 channels 0–15)
// ---------------------------------------------------------------------------
#define SERVO_CH_GRIP 0
#define SERVO_CH_BASE 1
#define SERVO_CH_SHOULDER 2
#define SERVO_CH_ELBOW 3

// ---------------------------------------------------------------------------
// Per-Joint Servo Calibration
//   Each servo has a unique angle↔pulse mapping, measured on hardware.
//   Two reference points define the linear mapping; pulse limits define
//   the physical safe range. MiraArm uses these for angle→tick conversion.
//
//   Per joint:  _CAL_LO_DEG / _CAL_LO_US  — low  reference (angle → µs)
//               _CAL_HI_DEG / _CAL_HI_US  — high reference (angle → µs)
//               _PULSE_MIN  / _PULSE_MAX   — hard pulse limits (µs)
// ---------------------------------------------------------------------------

// Base: ±90° maps to 400–2400 µs. No extension beyond.
#define SERVO_BASE_CAL_LO_DEG (-90.0f)
#define SERVO_BASE_CAL_LO_US 400
#define SERVO_BASE_CAL_HI_DEG 90.0f
#define SERVO_BASE_CAL_HI_US 2400
#define SERVO_BASE_PULSE_MIN 400
#define SERVO_BASE_PULSE_MAX 2400

// Shoulder: ±90° maps to 600–2500 µs. Extends to 400–2650 µs.
#define SERVO_SHOULDER_CAL_LO_DEG (-90.0f)
#define SERVO_SHOULDER_CAL_LO_US 600
#define SERVO_SHOULDER_CAL_HI_DEG 90.0f
#define SERVO_SHOULDER_CAL_HI_US 2500
#define SERVO_SHOULDER_PULSE_MIN 400
#define SERVO_SHOULDER_PULSE_MAX 2650

// Elbow: ±90° maps to 600–2500 µs. Extends to 270–2750 µs.
#define SERVO_ELBOW_CAL_LO_DEG (-90.0f)
#define SERVO_ELBOW_CAL_LO_US 600
#define SERVO_ELBOW_CAL_HI_DEG 90.0f
#define SERVO_ELBOW_CAL_HI_US 2500
#define SERVO_ELBOW_PULSE_MIN 270
#define SERVO_ELBOW_PULSE_MAX 2750

// Grip: ±90° maps to 600–2500 µs (estimated, not yet calibrated).
#define SERVO_GRIP_CAL_LO_DEG (-90.0f)
#define SERVO_GRIP_CAL_LO_US 600
#define SERVO_GRIP_CAL_HI_DEG 90.0f
#define SERVO_GRIP_CAL_HI_US 2500
#define SERVO_GRIP_PULSE_MIN 500
#define SERVO_GRIP_PULSE_MAX 2500

// Global angle bounds (widest range across all joints).
// Used for coarse console input validation only;
// per-joint clamping happens in MiraArm.
#define SERVO_ANGLE_MIN (-135)
#define SERVO_ANGLE_MAX 135

// ---------------------------------------------------------------------------
// Grip Presets (degrees, in the 0-centered system)
// ---------------------------------------------------------------------------
#define GRIP_OPEN_ANGLE (-30)
#define GRIP_CLOSED_ANGLE 45

// ---------------------------------------------------------------------------
// Home Position (degrees) — all servos go here on startup / reset
//   0° = servo center position for all joints.
// ---------------------------------------------------------------------------
#define HOME_GRIP GRIP_CLOSED_ANGLE
#define HOME_BASE 0
#define HOME_SHOULDER 0
#define HOME_ELBOW 0

// ---------------------------------------------------------------------------
// Arm Geometry (mm)
//   Coordinate system: X = forward, Y = left, Z = up
//   Origin: base rotation axis at table surface
// ---------------------------------------------------------------------------
#define ARM_BASE_HEIGHT 22.0f  // d0: base pivot to shoulder pivot (mm)
#define ARM_LINK1_LENGTH 40.0f // L1: shoulder pivot to elbow pivot (mm)
#define ARM_LINK2_LENGTH 86.0f // L2: elbow pivot to end effector (mm)

// ---------------------------------------------------------------------------
// Servo Direction Mapping
//   Maps IK geometric angles to servo PWM angles:
//   servo_angle = OFFSET + DIRECTION × geometric_angle_degrees
//   DIRECTION: +1.0 or -1.0. Tune on hardware.
//
//   Geometric 0° = arm horizontal (forward), 90° = arm vertical (up).
//   At home (servo 0°), the arm is vertical → geo 90° → offset = -90.
// ---------------------------------------------------------------------------
#define SERVO_BASE_OFFSET 0.0f
#define SERVO_BASE_DIRECTION 1.0f

#define SERVO_SHOULDER_OFFSET 90.0f
#define SERVO_SHOULDER_DIRECTION (-1.0f)

#define SERVO_ELBOW_OFFSET 0.0f
#define SERVO_ELBOW_DIRECTION (-1.0f)

// ---------------------------------------------------------------------------
// Per-Joint Angle Limits (servo degrees, after IK mapping)
//   Clamps IK solutions to the safe mechanical range for each joint.
//   These are physical constraints of the arm design.
// ---------------------------------------------------------------------------
#define JOINT_BASE_MIN (-90) // 400 µs (matches cal range exactly)
#define JOINT_BASE_MAX 90
#define JOINT_SHOULDER_MIN (-109) // 400 µs → ~-109° (from cal slope)
#define JOINT_SHOULDER_MAX 104    // 2650 µs → ~+104°
#define JOINT_ELBOW_MIN (-100)    // 270 µs → ~-121° physical, capped for safety
#define JOINT_ELBOW_MAX 100 // 2750 µs → ~+114° physical, capped for safety

// ---------------------------------------------------------------------------
// Test Routine Timing (milliseconds)
// ---------------------------------------------------------------------------
#define TEST_STEP_DELAY_MS 30   // Delay between each degree step
#define TEST_PAUSE_MS 500       // Pause between motion phases
#define TEST_LOOP_PAUSE_MS 2000 // Pause before restarting the test loop

// ---------------------------------------------------------------------------
// Status LED (onboard, GPIO 8)
// ---------------------------------------------------------------------------
#define LED_PIN 8
#define LED_PWM_FREQ 5000         // LEDC PWM frequency (Hz)
#define LED_PWM_RESOLUTION 8      // LEDC resolution (bits) → 0–255
#define LED_BREATH_PERIOD_MS 3000 // Full breath cycle duration (ms)
#define LED_ACTIVE_LOW true       // true = LED on when GPIO is LOW
#define LED_TASK_STACK 2048       // FreeRTOS task stack size (bytes)
#define LED_TASK_PRIORITY 1       // FreeRTOS task priority (low)

// ---------------------------------------------------------------------------
// Motion Planner
// ---------------------------------------------------------------------------
#define MOTION_UPDATE_INTERVAL_MS 5 // Interpolation rate (~200 Hz)
#define MOTION_DEFAULT_SPEED 50.0f  // Default end-effector speed (mm/s)
#define MOTION_QUEUE_SIZE 24        // Max waypoints in queue

// ---------------------------------------------------------------------------
// Smooth Mover (joint-space trapezoidal motion)
// ---------------------------------------------------------------------------
#define SMOOTH_DEFAULT_MAX_SPEED 120.0f // Max angular speed (deg/s)
#define SMOOTH_DEFAULT_ACCEL 300.0f     // Acceleration (deg/s²)
#define SMOOTH_UPDATE_INTERVAL_MS 5     // Update rate (~200 Hz)
#define SMOOTH_MAX_JOINTS 4             // Max simultaneous smooth moves

// ---------------------------------------------------------------------------
// BOOT Button (GPIO 9 on ESP32-C3 Super Mini, active LOW)
// Used after boot to cycle through gesture demo modes.
// ---------------------------------------------------------------------------
#define BOOT_BUTTON_PIN 9
#define BOOT_BUTTON_DEBOUNCE_MS 50 // Debounce window (ms)

// ---------------------------------------------------------------------------
// Serial
// ---------------------------------------------------------------------------
#define SERIAL_BAUD 115200

#endif // MIRA_CONFIG_H
