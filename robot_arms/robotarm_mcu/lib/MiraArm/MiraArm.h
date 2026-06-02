/**
 * MiraArm.h — Mira Robot Arm Controller
 *
 * High-level interface for controlling the 3-DOF arm (4 servos)
 * through a PCA9685 PWM driver.
 */

#ifndef MIRA_ARM_H
#define MIRA_ARM_H

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include "config.h"

class MiraArm {
public:
    MiraArm();

    /**
     * Initialize the PCA9685 and I2C bus.
     * Must be called once in setup().
     */
    void begin();

    /**
     * Set a servo to a specific angle (degrees).
     * @param channel  PCA9685 channel (0–15)
     * @param angle    Target angle (SERVO_ANGLE_MIN – SERVO_ANGLE_MAX)
     */
    void setServoAngle(uint8_t channel, float angle);

    /** Named servo setters (degrees) */
    void setGrip(float angle);
    void setBase(float angle);
    void setShoulder(float angle);
    void setElbow(float angle);

    /** Move all servos to their home positions (defined in config.h) */
    void home();

    /** Grip presets */
    void openGrip();
    void closeGrip();

    /**
     * Set a servo to a raw pulse width in microseconds.
     * Bypasses the angle mapping — for calibration and debugging.
     * @param channel  PCA9685 channel (0–15)
     * @param pulseUs  Pulse width in microseconds (0–20000)
     */
    void setServoRawUs(uint8_t channel, uint16_t pulseUs);

    /**
     * Disable PWM output on all servo channels (servos go limp).
     * Reduces power draw and mechanical wear when idle.
     * Any subsequent setServoAngle() call re-enables output automatically.
     */
    void sleep();

    /**
     * Re-enable PWM output after sleep().
     * Note: this only clears the sleeping flag — callers should
     * follow with setServoAngle() calls to restore servo positions.
     */
    void wake();

    /** Returns true if servos are currently disabled (sleeping). */
    bool isSleeping() const;

    /**
     * Smoothly sweep a single servo from one angle to another.
     * Uses blocking delay — suitable for test routines only.
     * @param channel   PCA9685 channel
     * @param fromAngle Starting angle (degrees)
     * @param toAngle   Ending angle (degrees)
     * @param stepDelay Delay between each 1° step (ms)
     */
    void sweep(uint8_t channel, float fromAngle, float toAngle, uint16_t stepDelay = TEST_STEP_DELAY_MS);

private:
    Adafruit_PWMServoDriver _pca;
    bool _sleeping;   ///< true when PWM outputs are disabled

    /**
     * Convert an angle in degrees to a PCA9685 tick count,
     * using per-channel calibration from config.h.
     */
    uint16_t _angleToTick(uint8_t channel, float angle);
};

#endif // MIRA_ARM_H
