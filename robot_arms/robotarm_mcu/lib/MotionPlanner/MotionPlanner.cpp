/**
 * MotionPlanner.cpp — Mira Motion Planner Implementation
 *
 * Linearly interpolates x, y, z, and grip between the current position
 * and each queued waypoint. Duration is computed from Euclidean distance
 * divided by the requested speed (mm/s).
 */

#include "MotionPlanner.h"

MotionPlanner::MotionPlanner(ArmController& ctrl)
    : _ctrl(ctrl),
      _head(0), _tail(0), _count(0),
      _interpolating(false),
      _startX(0), _startY(0), _startZ(0), _startGrip(0),
      _targetX(0), _targetY(0), _targetZ(0), _targetGrip(0),
      _moveStartMs(0), _moveDurationMs(0), _lastUpdateMs(0) {
}

// ---------------------------------------------------------------------------
// Queue operations
// ---------------------------------------------------------------------------

bool MotionPlanner::enqueue(float x, float y, float z, float grip, float speed) {
    if (_count >= MOTION_QUEUE_SIZE) {
        return false;  // Queue full
    }

    _queue[_head] = { x, y, z, grip, speed };
    _head = (_head + 1) % MOTION_QUEUE_SIZE;
    _count++;
    return true;
}

bool MotionPlanner::_dequeue(Waypoint& wp) {
    if (_count == 0) return false;

    wp = _queue[_tail];
    _tail = (_tail + 1) % MOTION_QUEUE_SIZE;
    _count--;
    return true;
}

void MotionPlanner::clearQueue() {
    _head = 0;
    _tail = 0;
    _count = 0;
    _interpolating = false;
}

void MotionPlanner::moveNow(float x, float y, float z, float grip) {
    clearQueue();
    _ctrl.moveTo(x, y, z);
    _ctrl.setGrip(grip);
}

uint8_t MotionPlanner::queueSize() const {
    return _count;
}

bool MotionPlanner::isBusy() const {
    return _interpolating || _count > 0;
}

bool MotionPlanner::isIdle() const {
    return !_interpolating && _count == 0;
}

// ---------------------------------------------------------------------------
// Interpolation
// ---------------------------------------------------------------------------

void MotionPlanner::_startInterpolation(const Waypoint& wp) {
    // Record start position
    _ctrl.getPosition(_startX, _startY, _startZ);
    _startGrip = _ctrl.getGrip();

    _targetX    = wp.x;
    _targetY    = wp.y;
    _targetZ    = wp.z;
    _targetGrip = wp.grip;

    if (wp.speed <= 0.0f) {
        // Instant move
        _ctrl.moveTo(wp.x, wp.y, wp.z);
        _ctrl.setGrip(wp.grip);
        _interpolating = false;
        return;
    }

    // Compute duration from distance and speed
    float dx = _targetX - _startX;
    float dy = _targetY - _startY;
    float dz = _targetZ - _startZ;
    float dist = sqrtf(dx * dx + dy * dy + dz * dz);

    // Minimum duration to avoid division issues on tiny moves
    uint32_t durationMs = (uint32_t)((dist / wp.speed) * 1000.0f);
    if (durationMs < MOTION_UPDATE_INTERVAL_MS) {
        durationMs = MOTION_UPDATE_INTERVAL_MS;
    }

    _moveDurationMs = durationMs;
    _moveStartMs    = millis();
    _interpolating  = true;
}

void MotionPlanner::update() {
    uint32_t now = millis();

    // Throttle update rate
    if (now - _lastUpdateMs < MOTION_UPDATE_INTERVAL_MS) {
        return;
    }
    _lastUpdateMs = now;

    // If not currently interpolating, try to start the next waypoint
    if (!_interpolating) {
        Waypoint wp;
        if (_dequeue(wp)) {
            _startInterpolation(wp);
        }
        // If _startInterpolation set _interpolating=false (instant move),
        // we'll pick up the next waypoint on the next update cycle.
        if (!_interpolating) return;
    }

    // Compute interpolation progress (0.0 – 1.0)
    uint32_t elapsed = now - _moveStartMs;
    float t = (float)elapsed / (float)_moveDurationMs;

    if (t >= 1.0f) {
        // Motion complete — snap to target
        _ctrl.moveTo(_targetX, _targetY, _targetZ);
        _ctrl.setGrip(_targetGrip);
        _interpolating = false;
        return;
    }

    // Smoothstep easing: zero velocity at start and end of each segment
    // f(t) = 3t² - 2t³  (Hermite smoothstep)
    float s = t * t * (3.0f - 2.0f * t);

    float x = _startX + (_targetX - _startX) * s;
    float y = _startY + (_targetY - _startY) * s;
    float z = _startZ + (_targetZ - _startZ) * s;
    float g = _startGrip + (_targetGrip - _startGrip) * s;

    _ctrl.moveTo(x, y, z);
    _ctrl.setGrip(g);
}
