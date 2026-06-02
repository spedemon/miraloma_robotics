/**
 * ArmController.cpp — Mira Arm Controller Implementation
 *
 * Inverse kinematics for a 3-DOF arm:
 *   - Base: vertical axis rotation (atan2 in XY plane)
 *   - Shoulder + Elbow: 2-link planar IK in the vertical plane
 */

#include "ArmController.h"

// Convenience
static const float RAD2DEG = 180.0f / M_PI;
static const float DEG2RAD = M_PI / 180.0f;

ArmController::ArmController(MiraArm& arm)
    : _arm(arm), _x(0), _y(0), _z(0), _grip(HOME_GRIP),
      _baseAngle(HOME_BASE), _shoulderAngle(HOME_SHOULDER), _elbowAngle(HOME_ELBOW) {
}

void ArmController::begin() {
    // Initialize tracked angles and compute Cartesian position via FK
    _baseAngle = HOME_BASE;
    _shoulderAngle = HOME_SHOULDER;
    _elbowAngle = HOME_ELBOW;
    _grip = HOME_GRIP;
    forwardKinematics(_baseAngle, _shoulderAngle, _elbowAngle, _x, _y, _z);

    Serial.print("[ArmController] Home position: X=");
    Serial.print(_x, 1);
    Serial.print(" Y=");
    Serial.print(_y, 1);
    Serial.print(" Z=");
    Serial.println(_z, 1);
}

// ---------------------------------------------------------------------------
// Servo ↔ geometric angle mapping
// ---------------------------------------------------------------------------

float ArmController::_geoToServoBase(float geoRad) const {
    return SERVO_BASE_OFFSET + SERVO_BASE_DIRECTION * (geoRad * RAD2DEG);
}

float ArmController::_geoToServoShoulder(float geoRad) const {
    return SERVO_SHOULDER_OFFSET + SERVO_SHOULDER_DIRECTION * (geoRad * RAD2DEG);
}

float ArmController::_geoToServoElbow(float geoRad) const {
    return SERVO_ELBOW_OFFSET + SERVO_ELBOW_DIRECTION * (geoRad * RAD2DEG);
}

float ArmController::_servoToGeoBase(float servoDeg) const {
    return ((servoDeg - SERVO_BASE_OFFSET) / SERVO_BASE_DIRECTION) * DEG2RAD;
}

float ArmController::_servoToGeoShoulder(float servoDeg) const {
    return ((servoDeg - SERVO_SHOULDER_OFFSET) / SERVO_SHOULDER_DIRECTION) * DEG2RAD;
}

float ArmController::_servoToGeoElbow(float servoDeg) const {
    return ((servoDeg - SERVO_ELBOW_OFFSET) / SERVO_ELBOW_DIRECTION) * DEG2RAD;
}

bool ArmController::_inLimits(float servoDeg, float minDeg, float maxDeg) const {
    return servoDeg >= minDeg && servoDeg <= maxDeg;
}

// ---------------------------------------------------------------------------
// Inverse Kinematics
// ---------------------------------------------------------------------------

bool ArmController::solve(float x, float y, float z,
                          float& baseAngle, float& shoulderAngle, float& elbowAngle) const {
    const float L1 = ARM_LINK1_LENGTH;
    const float L2 = ARM_LINK2_LENGTH;
    const float d0 = ARM_BASE_HEIGHT;

    // Step 1: Base angle (top-down view)
    float baseGeo = atan2f(y, x);

    // Step 2: 2-link planar IK in the vertical plane
    float r = sqrtf(x * x + y * y);     // Horizontal distance from base axis
    float zEff = z - d0;                 // Vertical distance from shoulder pivot

    float distSq = r * r + zEff * zEff;
    float D = (distSq - L1 * L1 - L2 * L2) / (2.0f * L1 * L2);

    // Check reachability
    if (D * D > 1.0f) {
        return false;  // Target is outside workspace
    }

    // Elbow angle (elbow-down solution: negative sqrt)
    // With SERVO_ELBOW_DIRECTION = -1, negative geo → positive servo angle.
    float elbowGeo = atan2f(-sqrtf(1.0f - D * D), D);

    // Shoulder angle
    float shoulderGeo = atan2f(zEff, r)
                      - atan2f(L2 * sinf(elbowGeo), L1 + L2 * cosf(elbowGeo));

    // Convert geometric angles to servo angles
    baseAngle     = _geoToServoBase(baseGeo);
    shoulderAngle = _geoToServoShoulder(shoulderGeo);
    elbowAngle    = _geoToServoElbow(elbowGeo);

    // Check joint limits
    if (!_inLimits(baseAngle, JOINT_BASE_MIN, JOINT_BASE_MAX) ||
        !_inLimits(shoulderAngle, JOINT_SHOULDER_MIN, JOINT_SHOULDER_MAX) ||
        !_inLimits(elbowAngle, JOINT_ELBOW_MIN, JOINT_ELBOW_MAX)) {
        return false;  // Valid IK solution but outside safe joint range
    }

    return true;
}

// ---------------------------------------------------------------------------
// Forward Kinematics
// ---------------------------------------------------------------------------

void ArmController::forwardKinematics(float baseServoDeg, float shoulderServoDeg, float elbowServoDeg,
                                       float& x, float& y, float& z) const {
    const float L1 = ARM_LINK1_LENGTH;
    const float L2 = ARM_LINK2_LENGTH;
    const float d0 = ARM_BASE_HEIGHT;

    // Convert servo angles back to geometric angles (radians)
    float baseGeo     = _servoToGeoBase(baseServoDeg);
    float shoulderGeo = _servoToGeoShoulder(shoulderServoDeg);
    float elbowGeo    = _servoToGeoElbow(elbowServoDeg);

    // Compute end-effector position in the vertical plane
    float r = L1 * cosf(shoulderGeo) + L2 * cosf(shoulderGeo + elbowGeo);
    float zEff = L1 * sinf(shoulderGeo) + L2 * sinf(shoulderGeo + elbowGeo);

    // Convert to 3D using base angle
    x = r * cosf(baseGeo);
    y = r * sinf(baseGeo);
    z = zEff + d0;
}

// ---------------------------------------------------------------------------
// Cartesian control
// ---------------------------------------------------------------------------

bool ArmController::moveTo(float x, float y, float z) {
    float baseAngle, shoulderAngle, elbowAngle;

    if (!solve(x, y, z, baseAngle, shoulderAngle, elbowAngle)) {
        return false;
    }

    _arm.setBase(baseAngle);
    _arm.setShoulder(shoulderAngle);
    _arm.setElbow(elbowAngle);

    // Update internal state
    _baseAngle = baseAngle;
    _shoulderAngle = shoulderAngle;
    _elbowAngle = elbowAngle;
    _x = x;
    _y = y;
    _z = z;

    return true;
}

void ArmController::setGrip(float angle) {
    // Clamp to configured range
    if (angle < GRIP_OPEN_ANGLE)   angle = GRIP_OPEN_ANGLE;
    if (angle > GRIP_CLOSED_ANGLE) angle = GRIP_CLOSED_ANGLE;

    _arm.setGrip(angle);
    _grip = angle;
}

void ArmController::home() {
    _arm.home();
    _baseAngle = HOME_BASE;
    _shoulderAngle = HOME_SHOULDER;
    _elbowAngle = HOME_ELBOW;
    _grip = HOME_GRIP;
    forwardKinematics(_baseAngle, _shoulderAngle, _elbowAngle, _x, _y, _z);
}

void ArmController::sleep() {
    _arm.sleep();
}

void ArmController::wake() {
    _arm.wake();
}

bool ArmController::isSleeping() const {
    return _arm.isSleeping();
}

void ArmController::setJointAngle(uint8_t channel, float angle) {
    _arm.setServoAngle(channel, angle);

    // Update tracked angle for the affected joint
    if (channel == SERVO_CH_BASE)          _baseAngle = angle;
    else if (channel == SERVO_CH_SHOULDER) _shoulderAngle = angle;
    else if (channel == SERVO_CH_ELBOW)    _elbowAngle = angle;
    else if (channel == SERVO_CH_GRIP)     { _grip = angle; return; }

    // Recompute Cartesian position from current servo angles
    forwardKinematics(_baseAngle, _shoulderAngle, _elbowAngle, _x, _y, _z);
}

// ---------------------------------------------------------------------------
// Query
// ---------------------------------------------------------------------------

void ArmController::getPosition(float& x, float& y, float& z) const {
    x = _x;
    y = _y;
    z = _z;
}

float ArmController::getGrip() const {
    return _grip;
}

float ArmController::getJointAngle(uint8_t channel) const {
    if (channel == SERVO_CH_BASE)     return _baseAngle;
    if (channel == SERVO_CH_SHOULDER) return _shoulderAngle;
    if (channel == SERVO_CH_ELBOW)    return _elbowAngle;
    if (channel == SERVO_CH_GRIP)     return _grip;
    return -1.0f;
}

void ArmController::getHomePosition(float& x, float& y, float& z) const {
    forwardKinematics(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, x, y, z);
}
