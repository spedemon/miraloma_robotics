/**
 * SmoothMover.cpp — Smooth Joint-Space Motion Implementation
 *
 * Trapezoidal velocity profile math:
 *
 *   Given distance d, max speed v, acceleration a:
 *
 *   d_accel = v² / (2a)     — distance to accelerate to v
 *
 *   If 2·d_accel >= d  →  triangular profile (can't reach full speed):
 *     t_accel = sqrt(d / a)
 *     v_peak  = a · t_accel
 *     t_total = 2 · t_accel
 *
 *   Else  →  trapezoidal profile:
 *     t_accel = v / a
 *     d_cruise = d - 2·d_accel
 *     t_cruise = d_cruise / v
 *     t_total  = 2·t_accel + t_cruise
 *
 *   Position at time t:
 *     Phase 1 (accel):  p = 0.5·a·t²
 *     Phase 2 (cruise): p = d_accel + v·(t - t_accel)
 *     Phase 3 (decel):  p = d - 0.5·a·(t_total - t)²
 */

#include "SmoothMover.h"

SmoothMover::SmoothMover(ArmController& ctrl)
    : _ctrl(ctrl),
      _lastUpdateMs(0),
      _maxSpeed(SMOOTH_DEFAULT_MAX_SPEED),
      _accel(SMOOTH_DEFAULT_ACCEL),
      _trackingActive(false),
      _trackingLastStepMs(0),
      _trackingLastCommandMs(0) {
    for (int i = 0; i < SMOOTH_MAX_JOINTS; i++) {
        _motions[i].active = false;
    }
    for (int i = 0; i < 3; i++) {
        _trackingTargets[i] = 0.0f;
        _trackingVelocities[i] = 0.0f;
    }
}

// ---------------------------------------------------------------------------
// Runtime parameters
// ---------------------------------------------------------------------------

void SmoothMover::setMaxSpeed(float degPerSec) {
    if (degPerSec > 0) _maxSpeed = degPerSec;
}

float SmoothMover::getMaxSpeed() const {
    return _maxSpeed;
}

void SmoothMover::setAcceleration(float degPerSecSq) {
    if (degPerSecSq > 0) _accel = degPerSecSq;
}

float SmoothMover::getAcceleration() const {
    return _accel;
}

// ---------------------------------------------------------------------------
// Slot management
// ---------------------------------------------------------------------------

int SmoothMover::_findSlot(uint8_t channel) const {
    // First pass: find an existing slot for this channel
    for (int i = 0; i < SMOOTH_MAX_JOINTS; i++) {
        if (_motions[i].active && _motions[i].channel == channel) {
            return i;
        }
    }
    // Second pass: find an empty slot
    for (int i = 0; i < SMOOTH_MAX_JOINTS; i++) {
        if (!_motions[i].active) {
            return i;
        }
    }
    return -1;
}

// ---------------------------------------------------------------------------
// Start / stop
// ---------------------------------------------------------------------------

void SmoothMover::startMove(uint8_t channel, float targetAngle) {
    if (_isArmChannel(channel)) {
        _stopTracking();
    }
    int slot = _findSlot(channel);
    if (slot < 0) {
        Serial.println("[SmoothMover] No available slot");
        return;
    }

    JointMotion& m = _motions[slot];

    // Determine current angle
    float currentAngle;
    if (m.active && m.channel == channel) {
        // Already mid-motion — compute where we are right now
        float elapsed = (millis() - m.startTimeMs) / 1000.0f;
        float disp = _evaluateProfile(m, elapsed);
        currentAngle = m.startAngle + m.direction * disp;
    } else {
        // Idle — read tracked angle from ArmController
        currentAngle = _ctrl.getJointAngle(channel);
    }

    // Compute distance
    float dist = fabsf(targetAngle - currentAngle);
    if (dist < 0.5f) {
        // Force servo to target — ensures hardware matches tracked state
        // (critical after sleep when physical position may differ)
        _ctrl.setJointAngle(channel, targetAngle);
        m.active = false;
        return;
    }

    m.active = true;
    m.channel = channel;
    m.startAngle = currentAngle;
    m.targetAngle = targetAngle;
    m.direction = (targetAngle > currentAngle) ? 1.0f : -1.0f;
    m.distance = dist;
    m.maxSpeed = _maxSpeed;
    m.accel = _accel;

    // Compute trapezoidal profile timing
    float dAccel = (m.maxSpeed * m.maxSpeed) / (2.0f * m.accel);

    if (2.0f * dAccel >= m.distance) {
        // Triangular profile — can't reach max speed
        m.tAccel = sqrtf(m.distance / m.accel);
        m.tCruise = 0.0f;
        m.tDecel = m.tAccel;
    } else {
        // Trapezoidal profile
        m.tAccel = m.maxSpeed / m.accel;
        float dCruise = m.distance - 2.0f * dAccel;
        m.tCruise = dCruise / m.maxSpeed;
        m.tDecel = m.tAccel;
    }

    m.tTotal = m.tAccel + m.tCruise + m.tDecel;
    m.startTimeMs = millis();
}

void SmoothMover::startCoordinatedMove(float baseAngle, float shoulderAngle,
                                        float elbowAngle) {
    _stopTracking();
    // Interactive XYZ control owns all three arm joints. Leave no stale arm
    // profile running when a new Cartesian target replaces the old one.
    stopJoint(SERVO_CH_BASE);
    stopJoint(SERVO_CH_SHOULDER);
    stopJoint(SERVO_CH_ELBOW);

    const uint8_t channels[3] = {
        SERVO_CH_BASE, SERVO_CH_SHOULDER, SERVO_CH_ELBOW
    };
    const float targets[3] = { baseAngle, shoulderAngle, elbowAngle };
    float distances[3];

    // Use one duration for every joint. With the fixed 25/50/25 trapezoid:
    //   maxSpeed = distance / (0.75 * duration)
    //   accel    = distance / (0.1875 * duration^2)
    // Choose the longest duration required by either limit for any joint.
    float durationSec = 0.05f;
    for (int i = 0; i < 3; i++) {
        distances[i] = fabsf(targets[i] - _ctrl.getJointAngle(channels[i]));
        if (distances[i] < 0.5f) continue;

        float speedDuration = distances[i] / (0.75f * _maxSpeed);
        float accelDuration = sqrtf(distances[i] / (0.1875f * _accel));
        durationSec = max(durationSec, max(speedDuration, accelDuration));
    }

    uint32_t nowMs = millis();
    for (int i = 0; i < 3; i++) {
        float currentAngle = _ctrl.getJointAngle(channels[i]);
        float dist = distances[i];

        if (dist < 0.5f) {
            _ctrl.setJointAngle(channels[i], targets[i]);
            continue;
        }

        int slot = _findSlot(channels[i]);
        if (slot < 0) continue;

        JointMotion& m = _motions[slot];
        m.active = true;
        m.channel = channels[i];
        m.startAngle = currentAngle;
        m.targetAngle = targets[i];
        m.direction = (targets[i] > currentAngle) ? 1.0f : -1.0f;
        m.distance = dist;
        m.tAccel = 0.25f * durationSec;
        m.tCruise = 0.50f * durationSec;
        m.tDecel = 0.25f * durationSec;
        m.tTotal = durationSec;
        m.maxSpeed = dist / (0.75f * durationSec);
        m.accel = m.maxSpeed / m.tAccel;
        m.startTimeMs = nowMs;
    }
}

void SmoothMover::setTrackingTarget(float baseAngle, float shoulderAngle,
                                    float elbowAngle) {
    const uint8_t channels[3] = {
        SERVO_CH_BASE, SERVO_CH_SHOULDER, SERVO_CH_ELBOW
    };
    const float targets[3] = { baseAngle, shoulderAngle, elbowAngle };

    if (!_trackingActive) {
        // A streaming target owns all arm joints atomically. Clear only their
        // one-shot profiles; grip motion may continue independently.
        for (int slot = 0; slot < SMOOTH_MAX_JOINTS; slot++) {
            if (_motions[slot].active && _isArmChannel(_motions[slot].channel)) {
                _motions[slot].active = false;
            }
        }
        for (int i = 0; i < 3; i++) {
            _trackingVelocities[i] = 0.0f;
        }
        _trackingActive = true;
        _trackingLastStepMs = millis();
    }

    for (int i = 0; i < 3; i++) {
        _trackingTargets[i] = targets[i];
    }
    _trackingLastCommandMs = millis();
}

bool SmoothMover::isTracking() const {
    return _trackingActive;
}

bool SmoothMover::_isArmChannel(uint8_t channel) const {
    return channel == SERVO_CH_BASE || channel == SERVO_CH_SHOULDER ||
           channel == SERVO_CH_ELBOW;
}

void SmoothMover::_stopTracking() {
    _trackingActive = false;
    for (int i = 0; i < 3; i++) {
        _trackingVelocities[i] = 0.0f;
    }
}

void SmoothMover::_updateTracking(uint32_t now) {
    if (!_trackingActive) return;

    float dt = (now - _trackingLastStepMs) / 1000.0f;
    _trackingLastStepMs = now;
    if (dt <= 0.0f) return;
    if (dt > 0.05f) dt = 0.05f;  // Avoid a large jump after a stalled loop.

    const uint8_t channels[3] = {
        SERVO_CH_BASE, SERVO_CH_SHOULDER, SERVO_CH_ELBOW
    };
    bool settled = true;

    for (int i = 0; i < 3; i++) {
        float current = _ctrl.getJointAngle(channels[i]);
        float error = _trackingTargets[i] - current;
        float absError = fabsf(error);

        // The braking-speed bound guarantees that the joint can stop at the
        // moving target under the configured acceleration limit.
        float desiredSpeed = sqrtf(2.0f * _accel * absError);
        desiredSpeed = min(desiredSpeed, _maxSpeed);
        float desiredVelocity = error < 0.0f ? -desiredSpeed : desiredSpeed;
        if (absError <= TRACKING_POSITION_EPSILON) desiredVelocity = 0.0f;

        float maxVelocityChange = _accel * dt;
        float velocityChange = desiredVelocity - _trackingVelocities[i];
        velocityChange = max(-maxVelocityChange,
                             min(maxVelocityChange, velocityChange));
        _trackingVelocities[i] += velocityChange;

        float step = _trackingVelocities[i] * dt;
        if (absError <= TRACKING_POSITION_EPSILON &&
            fabsf(_trackingVelocities[i]) <= TRACKING_VELOCITY_EPSILON) {
            current = _trackingTargets[i];
            _trackingVelocities[i] = 0.0f;
        } else {
            current += step;
        }
        _ctrl.setJointAngle(channels[i], current);

        if (fabsf(_trackingTargets[i] - current) > TRACKING_POSITION_EPSILON ||
            fabsf(_trackingVelocities[i]) > TRACKING_VELOCITY_EPSILON) {
            settled = false;
        }
    }

    // A dropped browser or radio link cannot leave a perpetual live-control
    // mode behind. Finish at the last safe target, then release the joints.
    if (settled && now - _trackingLastCommandMs >= TRACKING_COMMAND_TIMEOUT_MS) {
        _stopTracking();
    }
}

void SmoothMover::startTimedMove(float baseAngle, float shoulderAngle,
                                  float elbowAngle, float gripAngle,
                                  uint32_t durationMs) {
    // Stop any existing motions
    stopAll();

    if (durationMs < 50) durationMs = 50;  // Safety floor

    float tTotal = durationMs / 1000.0f;  // Convert to seconds

    // Target angles for each channel
    const uint8_t channels[4] = {
        SERVO_CH_BASE, SERVO_CH_SHOULDER, SERVO_CH_ELBOW, SERVO_CH_GRIP
    };
    const float targets[4] = { baseAngle, shoulderAngle, elbowAngle, gripAngle };

    uint32_t nowMs = millis();

    for (int i = 0; i < 4; i++) {
        float currentAngle = _ctrl.getJointAngle(channels[i]);
        float dist = fabsf(targets[i] - currentAngle);

        if (dist < 0.5f) {
            // Force servo to target — ensures hardware matches tracked state
            _ctrl.setJointAngle(channels[i], targets[i]);
            continue;
        }

        int slot = _findSlot(channels[i]);
        if (slot < 0) continue;  // No slot available (shouldn't happen with 4 slots)

        JointMotion& m = _motions[slot];

        m.active = true;
        m.channel = channels[i];
        m.startAngle = currentAngle;
        m.targetAngle = targets[i];
        m.direction = (targets[i] > currentAngle) ? 1.0f : -1.0f;
        m.distance = dist;

        // Back-compute speed and accel from desired total time
        // Profile: 25% accel, 50% cruise, 25% decel
        m.tAccel  = 0.25f * tTotal;
        m.tCruise = 0.50f * tTotal;
        m.tDecel  = 0.25f * tTotal;
        m.tTotal  = tTotal;

        // maxSpeed = distance / (tAccel + tCruise)  [area under trapezoidal curve]
        // For trapezoidal: distance = 0.5*v*tAccel + v*tCruise + 0.5*v*tDecel
        //                           = v * (0.5*tAccel + tCruise + 0.5*tDecel)
        //                           = v * 0.75 * tTotal
        m.maxSpeed = dist / (0.75f * tTotal);
        m.accel    = m.maxSpeed / m.tAccel;

        m.startTimeMs = nowMs;
    }
}

void SmoothMover::stopAll() {
    _stopTracking();
    for (int i = 0; i < SMOOTH_MAX_JOINTS; i++) {
        _motions[i].active = false;
    }
}

void SmoothMover::stopJoint(uint8_t channel) {
    for (int i = 0; i < SMOOTH_MAX_JOINTS; i++) {
        if (_motions[i].active && _motions[i].channel == channel) {
            _motions[i].active = false;
            return;
        }
    }
}

bool SmoothMover::isBusy() const {
    if (_trackingActive) return true;
    for (int i = 0; i < SMOOTH_MAX_JOINTS; i++) {
        if (_motions[i].active) return true;
    }
    return false;
}

bool SmoothMover::isJointBusy(uint8_t channel) const {
    if (_trackingActive && _isArmChannel(channel)) return true;
    for (int i = 0; i < SMOOTH_MAX_JOINTS; i++) {
        if (_motions[i].active && _motions[i].channel == channel) return true;
    }
    return false;
}

// ---------------------------------------------------------------------------
// Trapezoidal profile evaluation
// ---------------------------------------------------------------------------

float SmoothMover::_evaluateProfile(const JointMotion& m, float t) const {
    if (t <= 0.0f) return 0.0f;
    if (t >= m.tTotal) return m.distance;

    float a = m.accel;
    float v = m.maxSpeed;

    // For triangular profiles, the peak speed is less than maxSpeed
    if (m.tCruise <= 0.0f) {
        v = a * m.tAccel;  // Actual peak speed
    }

    if (t < m.tAccel) {
        // Phase 1: Acceleration
        return 0.5f * a * t * t;
    }

    float dAccel = 0.5f * a * m.tAccel * m.tAccel;

    if (t < m.tAccel + m.tCruise) {
        // Phase 2: Cruise
        return dAccel + v * (t - m.tAccel);
    }

    // Phase 3: Deceleration
    float tRemaining = m.tTotal - t;
    return m.distance - 0.5f * a * tRemaining * tRemaining;
}

// ---------------------------------------------------------------------------
// Update loop
// ---------------------------------------------------------------------------

void SmoothMover::update() {
    uint32_t now = millis();

    // Throttle update rate
    if (now - _lastUpdateMs < SMOOTH_UPDATE_INTERVAL_MS) {
        return;
    }
    _lastUpdateMs = now;

    _updateTracking(now);

    for (int i = 0; i < SMOOTH_MAX_JOINTS; i++) {
        JointMotion& m = _motions[i];
        if (!m.active) continue;

        float elapsed = (now - m.startTimeMs) / 1000.0f;

        if (elapsed >= m.tTotal) {
            // Motion complete — snap to target
            _ctrl.setJointAngle(m.channel, m.targetAngle);
            m.active = false;
            continue;
        }

        // Evaluate trapezoidal position
        float displacement = _evaluateProfile(m, elapsed);
        float angle = m.startAngle + m.direction * displacement;
        _ctrl.setJointAngle(m.channel, angle);
    }
}
