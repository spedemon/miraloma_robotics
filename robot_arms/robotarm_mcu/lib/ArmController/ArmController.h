/**
 * ArmController.h — Mira Arm Controller (Layer 1)
 *
 * Provides Cartesian end-effector control via inverse kinematics
 * and grip angle control. Builds on top of MiraArm (Layer 0).
 *
 * Coordinate system (right-handed):
 *   X = forward (away from robot)
 *   Y = left
 *   Z = up
 *   Origin = base rotation axis at table surface
 */

#ifndef MIRA_ARM_CONTROLLER_H
#define MIRA_ARM_CONTROLLER_H

#include <Arduino.h>
#include <math.h>
#include "config.h"
#include "MiraArm.h"

class ArmController {
public:
    ArmController(MiraArm& arm);

    /**
     * Initialize the controller. Call after MiraArm::begin().
     * Computes initial FK from home angles.
     */
    void begin();

    // ----- Cartesian control (instant) -----

    /**
     * Move end effector to Cartesian position immediately.
     * @return true if reachable, false if target is outside workspace.
     */
    bool moveTo(float x, float y, float z);

    /**
     * Set grip angle immediately.
     * @param angle  Grip angle (GRIP_OPEN_ANGLE to GRIP_CLOSED_ANGLE)
     */
    void setGrip(float angle);

    /**
     * Move all joints to home position (angle-based).
     * Updates internal Cartesian state via FK.
     */
    void home();

    /**
     * Set a single joint's servo angle directly (degrees).
     * Updates internal state via FK so `where` stays consistent.
     * @param channel  PCA9685 channel (use SERVO_CH_BASE etc.)
     * @param angle    Servo angle (degrees)
     */
    void setJointAngle(uint8_t channel, float angle);

    // ----- Query -----

    /** Get current end-effector position (from last FK computation). */
    void getPosition(float& x, float& y, float& z) const;

    /** Get current grip angle. */
    float getGrip() const;

    /**
     * Get the tracked servo angle for a joint (degrees).
     * @param channel  PCA9685 channel (SERVO_CH_BASE, etc.)
     * @return Current servo angle, or -1 if channel not tracked.
     */
    float getJointAngle(uint8_t channel) const;

    /**
     * Compute home position in Cartesian coordinates.
     * Useful for knowing where "home" is in x,y,z space.
     */
    void getHomePosition(float& x, float& y, float& z) const;

    // ----- IK solver (no motion) -----

    /**
     * Solve inverse kinematics without moving servos.
     * @param x,y,z      Target position (mm)
     * @param baseAngle   Output: base servo angle (degrees)
     * @param shoulderAngle Output: shoulder servo angle (degrees)
     * @param elbowAngle  Output: elbow servo angle (degrees)
     * @return true if a valid solution was found within joint limits.
     */
    bool solve(float x, float y, float z,
               float& baseAngle, float& shoulderAngle, float& elbowAngle) const;

    // ----- Forward kinematics -----

    /**
     * Compute end-effector position from servo angles.
     * @param baseAngle, shoulderAngle, elbowAngle  Servo angles (degrees)
     * @param x, y, z  Output: Cartesian position (mm)
     */
    void forwardKinematics(float baseAngle, float shoulderAngle, float elbowAngle,
                           float& x, float& y, float& z) const;

private:
    MiraArm& _arm;

    // Current state (updated after every move)
    float _x, _y, _z;
    float _grip;

    // Tracked servo angles (degrees) — kept in sync for FK
    float _baseAngle, _shoulderAngle, _elbowAngle;

    // ----- Servo ↔ geometric angle mapping -----

    /** Convert IK geometric angle (radians) to servo angle (degrees). */
    float _geoToServoBase(float geoRad) const;
    float _geoToServoShoulder(float geoRad) const;
    float _geoToServoElbow(float geoRad) const;

    /** Convert servo angle (degrees) to IK geometric angle (radians). */
    float _servoToGeoBase(float servoDeg) const;
    float _servoToGeoShoulder(float servoDeg) const;
    float _servoToGeoElbow(float servoDeg) const;

    /** Check if a servo angle is within configured joint limits. */
    bool _inLimits(float servoDeg, float minDeg, float maxDeg) const;
};

#endif // MIRA_ARM_CONTROLLER_H
