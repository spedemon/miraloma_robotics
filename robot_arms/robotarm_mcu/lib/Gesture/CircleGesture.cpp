/**
 * CircleGesture.cpp — Smooth circle via parametric real-time computation
 *
 * Instead of discrete waypoints through the MotionPlanner, this computes
 * the exact (x,y,z) position on the circle using sin/cos every 20ms tick.
 * Bypasses the MotionPlanner entirely for perfectly smooth motion.
 *
 * Side-view circle in XZ plane (Y=0). Center: (64, 108), R=16mm.
 */

#include "CircleGesture.h"
#include <math.h>

// Circle parameters
static const float CX = 64.0f;
static const float CZ = 108.0f;
static const float CR = 16.0f;

// Angular speed: radians per millisecond.
// At default speed=40: one full revolution = 2*pi*R / speed ≈ 2.5 seconds.
static const float BASE_ANGULAR_SPEED = 1.0f / 1000.0f;  // rad/ms at speed=1

CircleGesture::CircleGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(75.0f), _phase(0) {
}

void CircleGesture::start() {
    _running = true;
    _phase = 0;
    _planner.clearQueue();
    _angleRad = 0.0f;
    _lastTickMs = millis();

    // Smooth lead-in: travel to the starting point of the circle
    float startX = CX + CR;  // cos(0) = 1
    float startZ = CZ;       // sin(0) = 0
    _planner.enqueue(startX, 0.0f, startZ, _ctrl.getGrip(), _speed);
    _leadIn = true;

    Serial.println("[Gesture] Circle started");
}

void CircleGesture::stop() {
    _running = false;
    _ctrl.home();
    Serial.println("[Gesture] Circle stopped");
}

void CircleGesture::update() {
    if (!_running) return;

    // Wait for lead-in to finish before starting parametric loop
    if (_leadIn) {
        if (_planner.isIdle()) {
            _leadIn = false;
            _lastTickMs = millis();
        }
        return;
    }

    uint32_t now = millis();
    uint32_t dt = now - _lastTickMs;
    if (dt < 5) return;  // ~200 Hz
    _lastTickMs = now;

    // Advance angle based on speed
    // speed is in mm/s, angular speed = speed / R (in rad/s)
    float angularSpeed = _speed / CR;  // rad/s
    _angleRad += angularSpeed * (dt / 1000.0f);

    // Wrap angle
    if (_angleRad >= 2.0f * M_PI) {
        _angleRad -= 2.0f * M_PI;
    }

    // Compute exact position on circle
    float x = CX + CR * cosf(_angleRad);
    float z = CZ + CR * sinf(_angleRad);

    _ctrl.moveTo(x, 0.0f, z);
}

bool CircleGesture::isRunning() { return _running; }
void CircleGesture::setSpeed(float speed) { _speed = speed; }

// Unused but required by interface
void CircleGesture::_enqueueNextPhase() {}
