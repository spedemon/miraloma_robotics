/**
 * SquareGesture.cpp — Smooth square via edge-walking
 *
 * Linearly interpolates along each edge at 50Hz, pausing briefly at
 * each corner. Bypasses MotionPlanner for smooth continuous motion.
 *
 * Side-view square in XZ plane (Y=0). Center (64, 108), side=22.6mm.
 */

#include "SquareGesture.h"

static const float SQ_Y = 0.0f;
static const uint32_t CORNER_HOLD_MS = 200;

// 4 corners: top-right, top-left, bottom-left, bottom-right
struct Vec2 { float a, b; };
static const Vec2 CORNERS[] = {
    { 75.3f, 119.3f },  // 0: top-right   (X, Z)
    { 52.7f, 119.3f },  // 1: top-left
    { 52.7f,  96.7f },  // 2: bottom-left
    { 75.3f,  96.7f },  // 3: bottom-right
};

SquareGesture::SquareGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(75.0f),
      _edge(0), _t(0.0f), _lastTickMs(0), _holdStartMs(0), _holding(false) {
}

void SquareGesture::start() {
    _running = true;
    _planner.clearQueue();
    _edge = 0; _t = 0.0f; _holding = false;
    _lastTickMs = millis();

    // Smooth lead-in: travel to the first corner
    _planner.enqueue(CORNERS[0].a, SQ_Y, CORNERS[0].b, _ctrl.getGrip(), _speed);
    _leadIn = true;

    Serial.println("[Gesture] Square started");
}

void SquareGesture::stop() {
    _running = false;
    _ctrl.home();
    Serial.println("[Gesture] Square stopped");
}

void SquareGesture::update() {
    if (!_running) return;

    // Wait for lead-in to finish before starting edge-walk
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

    if (_holding) {
        // Pause at corner
        if (now - _holdStartMs >= CORNER_HOLD_MS) {
            _holding = false;
            _edge = (_edge + 1) % 4;
            _t = 0.0f;
        }
        return;
    }

    // Edge length
    uint8_t next = (_edge + 1) % 4;
    float dx = CORNERS[next].a - CORNERS[_edge].a;
    float dz = CORNERS[next].b - CORNERS[_edge].b;
    float edgeLen = sqrtf(dx * dx + dz * dz);

    // Advance t based on speed and edge length
    _t += (_speed * (dt / 1000.0f)) / edgeLen;

    if (_t >= 1.0f) {
        // Arrived at corner — snap to exact position and hold
        _t = 1.0f;
        _ctrl.moveTo(CORNERS[next].a, SQ_Y, CORNERS[next].b);
        _holding = true;
        _holdStartMs = now;
        return;
    }

    // Interpolate along edge
    float x = CORNERS[_edge].a + dx * _t;
    float z = CORNERS[_edge].b + dz * _t;
    _ctrl.moveTo(x, SQ_Y, z);
}

bool SquareGesture::isRunning() { return _running; }
void SquareGesture::setSpeed(float speed) { _speed = speed; }
