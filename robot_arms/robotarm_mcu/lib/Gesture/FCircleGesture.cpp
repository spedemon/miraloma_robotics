/**
 * FCircleGesture.cpp — Smooth front-facing circle via parametric computation
 *
 * Circle in YZ plane at X=90. Center: (Y=-2, Z=58), R=44mm.
 * Computes exact position using sin/cos every tick.
 */

#include "FCircleGesture.h"
#include <math.h>

static const float FX  = 90.0f;
static const float FCY = -2.0f;
static const float FCZ = 58.0f;
static const float FR  = 44.0f;

FCircleGesture::FCircleGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(75.0f), _angleRad(0.0f), _lastTickMs(0) {
}

void FCircleGesture::start() {
    _running = true;
    _planner.clearQueue();
    _angleRad = 0.0f;
    _lastTickMs = millis();
    Serial.println("[Gesture] FCircle started");
}

void FCircleGesture::stop() {
    _running = false;
    _ctrl.home();
    Serial.println("[Gesture] FCircle stopped");
}

void FCircleGesture::update() {
    if (!_running) return;

    uint32_t now = millis();
    uint32_t dt = now - _lastTickMs;
    if (dt < 5) return;  // ~200 Hz
    _lastTickMs = now;

    float angularSpeed = _speed / FR;
    _angleRad += angularSpeed * (dt / 1000.0f);
    if (_angleRad >= 2.0f * M_PI) _angleRad -= 2.0f * M_PI;

    float y = FCY + FR * cosf(_angleRad);
    float z = FCZ + FR * sinf(_angleRad);

    _ctrl.moveTo(FX, y, z);
}

bool FCircleGesture::isRunning() { return _running; }
void FCircleGesture::setSpeed(float speed) { _speed = speed; }
