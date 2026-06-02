/**
 * TriangleGesture.cpp — Smooth triangle via edge-walking
 *
 * Linearly interpolates along each edge at 50Hz, pausing at vertices.
 * Side-view in XZ plane (Y=0). Center (64, 108), R=16mm.
 */

#include "TriangleGesture.h"

static const float TRI_Y = 0.0f;
static const uint32_t VERTEX_HOLD_MS = 200;

struct Vec2 { float a, b; };
static const Vec2 VERTICES[] = {
    { 64.0f, 124.0f },  // 0: top
    { 50.1f, 100.0f },  // 1: bottom-left
    { 77.9f, 100.0f },  // 2: bottom-right
};

TriangleGesture::TriangleGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(75.0f),
      _edge(0), _t(0.0f), _lastTickMs(0), _holdStartMs(0), _holding(false) {
}

void TriangleGesture::start() {
    _running = true;
    _planner.clearQueue();
    _edge = 0; _t = 0.0f; _holding = false;
    _lastTickMs = millis();

    // Smooth lead-in: travel to the first vertex
    _planner.enqueue(VERTICES[0].a, TRI_Y, VERTICES[0].b, _ctrl.getGrip(), _speed);
    _leadIn = true;

    Serial.println("[Gesture] Triangle started");
}

void TriangleGesture::stop() {
    _running = false;
    _ctrl.home();
    Serial.println("[Gesture] Triangle stopped");
}

void TriangleGesture::update() {
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
        if (now - _holdStartMs >= VERTEX_HOLD_MS) {
            _holding = false;
            _edge = (_edge + 1) % 3;
            _t = 0.0f;
        }
        return;
    }

    uint8_t next = (_edge + 1) % 3;
    float dx = VERTICES[next].a - VERTICES[_edge].a;
    float dz = VERTICES[next].b - VERTICES[_edge].b;
    float edgeLen = sqrtf(dx * dx + dz * dz);

    _t += (_speed * (dt / 1000.0f)) / edgeLen;

    if (_t >= 1.0f) {
        _t = 1.0f;
        _ctrl.moveTo(VERTICES[next].a, TRI_Y, VERTICES[next].b);
        _holding = true;
        _holdStartMs = now;
        return;
    }

    float x = VERTICES[_edge].a + dx * _t;
    float z = VERTICES[_edge].b + dz * _t;
    _ctrl.moveTo(x, TRI_Y, z);
}

bool TriangleGesture::isRunning() { return _running; }
void TriangleGesture::setSpeed(float speed) { _speed = speed; }
