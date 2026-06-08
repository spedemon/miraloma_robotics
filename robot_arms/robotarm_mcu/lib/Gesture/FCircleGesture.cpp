/**
 * FCircleGesture.cpp — Smooth front-facing circle via parametric computation
 *
 * Circle in YZ plane at X=90. Center: (Y=-2, Z=58), R=44mm.
 * Rotated -30° from frontal. Computes exact position using sin/cos every tick.
 */

#include "FCircleGesture.h"
#include <math.h>

static const float FX  = 90.0f;
static const float FCY = -2.0f;
static const float FCZ = 58.0f;
static const float FR  = 44.0f;
static const float ROT_ANGLE = -M_PI / 6.0f;  // -30° rotation

FCircleGesture::FCircleGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth)
    : _planner(planner), _ctrl(ctrl), _smooth(smooth),
      _running(false), _speed(75.0f), _angleRad(0.0f), _lastTickMs(0) {
}

void FCircleGesture::start() {
    _running = true;
    _planner.clearQueue();
    _angleRad = 0.0f;
    _lastTickMs = millis();

    // Smooth lead-in: travel to the starting point of the circle
    float startY = FCY + FR;  // cos(0) = 1
    float startZ = FCZ;       // sin(0) = 0
    float rotX = FX * cosf(ROT_ANGLE) - startY * sinf(ROT_ANGLE);
    float rotY = FX * sinf(ROT_ANGLE) + startY * cosf(ROT_ANGLE);
    _planner.enqueue(rotX, rotY, startZ, _ctrl.getGrip(), _speed);
    _leadIn = true;

    Serial.println("[Gesture] FCircle started");
}

void FCircleGesture::stop() {
    _running = false;
    // Smooth return to home (1s) instead of instant snap
    _smooth.startTimedMove(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, HOME_GRIP, 1000);
    Serial.println("[Gesture] FCircle stopped");
}

void FCircleGesture::update() {
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

    float angularSpeed = _speed / FR;
    _angleRad += angularSpeed * (dt / 1000.0f);
    if (_angleRad >= 2.0f * M_PI) _angleRad -= 2.0f * M_PI;

    float y = FCY + FR * cosf(_angleRad);
    float z = FCZ + FR * sinf(_angleRad);

    float rotX = FX * cosf(ROT_ANGLE) - y * sinf(ROT_ANGLE);
    float rotY = FX * sinf(ROT_ANGLE) + y * cosf(ROT_ANGLE);

    _ctrl.moveTo(rotX, rotY, z);
}

bool FCircleGesture::isRunning() { return _running; }
void FCircleGesture::setSpeed(float speed) { _speed = speed; }
