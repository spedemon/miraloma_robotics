/**
 * SmoothMover.h — Smooth Joint-Space Motion
 *
 * Moves individual servos using trapezoidal velocity profiles:
 *   Phase 1: Accelerate from 0 to maxSpeed
 *   Phase 2: Cruise at maxSpeed
 *   Phase 3: Decelerate from maxSpeed to 0
 *
 * For short moves where maxSpeed can't be reached, uses a
 * triangular profile (accelerate then decelerate).
 *
 * Supports up to SMOOTH_MAX_JOINTS simultaneous motions.
 * Non-blocking — call update() every loop() iteration.
 */

#ifndef MIRA_SMOOTH_MOVER_H
#define MIRA_SMOOTH_MOVER_H

#include <Arduino.h>
#include "config.h"
#include "ArmController.h"

struct JointMotion {
    bool     active;
    uint8_t  channel;       // PCA9685 channel
    float    startAngle;    // degrees
    float    targetAngle;   // degrees
    float    direction;     // +1.0 or -1.0
    float    distance;      // total angular distance (positive)

    // Trapezoidal profile timing (seconds)
    float    tAccel;        // acceleration phase duration
    float    tCruise;       // cruise phase duration
    float    tDecel;        // deceleration phase duration
    float    tTotal;        // total move duration

    // Profile parameters used for this move
    float    maxSpeed;      // deg/s
    float    accel;         // deg/s²

    uint32_t startTimeMs;   // millis() when the move started
};

class SmoothMover {
public:
    SmoothMover(ArmController& ctrl);

    /**
     * Update all active motions. Call every loop() iteration.
     * Self-throttles to SMOOTH_UPDATE_INTERVAL_MS.
     */
    void update();

    /**
     * Start a smooth move for a single joint.
     * If this joint already has an active move, it is replaced.
     *
     * @param channel     PCA9685 channel (SERVO_CH_BASE, etc.)
     * @param targetAngle Target angle in degrees
     */
    void startMove(uint8_t channel, float targetAngle);

    /**
     * Stop all active smooth motions immediately.
     */
    void stopAll();

    /**
     * Stop a specific joint's smooth motion.
     */
    void stopJoint(uint8_t channel);

    /** Is any joint currently moving? */
    bool isBusy() const;

    /** Is a specific joint currently moving? */
    bool isJointBusy(uint8_t channel) const;

    // ----- Runtime parameters -----

    void  setMaxSpeed(float degPerSec);
    float getMaxSpeed() const;

    void  setAcceleration(float degPerSecSq);
    float getAcceleration() const;

    /**
     * Start a coordinated timed move for all four joints.
     * All joints arrive at their targets simultaneously in exactly durationMs.
     * Uses trapezoidal profiles with per-joint speed/accel computed from
     * the requested duration (25% accel, 50% cruise, 25% decel).
     *
     * @param baseAngle, shoulderAngle, elbowAngle, gripAngle  Target angles (degrees)
     * @param durationMs  Total move duration in milliseconds (minimum 50ms)
     */
    void startTimedMove(float baseAngle, float shoulderAngle,
                        float elbowAngle, float gripAngle,
                        uint32_t durationMs);

private:
    ArmController& _ctrl;

    JointMotion _motions[SMOOTH_MAX_JOINTS];
    uint32_t    _lastUpdateMs;

    float _maxSpeed;    // deg/s (runtime adjustable)
    float _accel;       // deg/s² (runtime adjustable)

    /**
     * Find the motion slot for a channel, or an empty slot.
     * Returns index, or -1 if no slot available.
     */
    int _findSlot(uint8_t channel) const;

    /**
     * Evaluate the trapezoidal position at time t for a given motion.
     * Returns the angular displacement from startAngle (always positive).
     */
    float _evaluateProfile(const JointMotion& m, float t) const;
};

#endif // MIRA_SMOOTH_MOVER_H
