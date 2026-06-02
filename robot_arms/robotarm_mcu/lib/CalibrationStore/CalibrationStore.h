/**
 * CalibrationStore.h — Per-Joint Servo Calibration Offsets
 *
 * Stores and retrieves per-joint calibration offsets in ESP32 NVS flash.
 * Offsets are additive: servo_angle_actual = commanded_angle + offset.
 * This compensates for per-unit servo mounting differences so that
 * software 0° matches the physical home position on every robot.
 *
 * Usage:
 *   CalibrationStore cal;
 *   cal.begin();                        // Load from flash (or defaults)
 *   float off = cal.getOffset(channel); // Use in angle→tick conversion
 *   cal.setOffsets(3.5, -2.0, 1.5, 0);  // Save new offsets to flash
 *   cal.resetOffsets();                  // Clear all to 0.0
 */

#ifndef MIRA_CALIBRATION_STORE_H
#define MIRA_CALIBRATION_STORE_H

#include <Arduino.h>
#include "config.h"

class CalibrationStore {
public:
    CalibrationStore();

    /**
     * Load calibration offsets from NVS flash.
     * If no offsets are stored, defaults to 0.0 for all joints.
     * Must be called once in setup(), before any servo commands.
     */
    void begin();

    /**
     * Get the calibration offset for a specific servo channel.
     * @param channel  PCA9685 channel (SERVO_CH_BASE, etc.)
     * @return Offset in degrees (added to commanded angle)
     */
    float getOffset(uint8_t channel) const;

    /**
     * Save new calibration offsets to NVS flash.
     * Takes effect immediately for subsequent angle→tick conversions.
     * @param base, shoulder, elbow, grip  Offsets in degrees
     */
    void setOffsets(float base, float shoulder, float elbow, float grip);

    /**
     * Reset all offsets to 0.0 and clear from flash.
     */
    void resetOffsets();

    /**
     * Retrieve all four offsets at once.
     */
    void getOffsets(float& base, float& shoulder, float& elbow, float& grip) const;

private:
    float _offsets[4];  // Indexed by SERVO_CH_* (0=grip, 1=base, 2=shoulder, 3=elbow)

    void _save();       // Write current offsets to NVS
    void _load();       // Read offsets from NVS
};

#endif // MIRA_CALIBRATION_STORE_H
