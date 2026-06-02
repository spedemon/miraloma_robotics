/**
 * FTriangleGesture.cpp — Smooth front-facing triangle via edge-walking
 *
 * YZ plane at X=90. Center (Y=-2, Z=58), R=44mm, equilateral.
 */

#include "FTriangleGesture.h"

static const float FTRI_X = 90.0f;
static const uint32_t VERTEX_HOLD_MS = 200;

struct FVec2 { float y, z; };
static const FVec2 FVERTICES[] = {
    {  -2.0f, 102.2f },  // 0: top
    { -40.3f,  35.9f },  // 1: bottom-left
    {  36.3f,  35.9f },  // 2: bottom-right
};

FTriangleGesture::FTriangleGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(75.0f),
      _edge(0), _t(0.0f), _lastTickMs(0), _holdStartMs(0), _holding(false) {
}

void FTriangleGesture::start() {
    _running = true;
    _planner.clearQueue();
    _edge = 0; _t = 0.0f; _holding = false;
    _lastTickMs = millis();
    Serial.println("[Gesture] FTriangle started");
}

void FTriangleGesture::stop() {
    _running = false;
    _ctrl.home();
    Serial.println("[Gesture] FTriangle stopped");
}

void FTriangleGesture::update() {
    if (!_running) return;

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
    float dy = FVERTICES[next].y - FVERTICES[_edge].y;
    float dz = FVERTICES[next].z - FVERTICES[_edge].z;
    float edgeLen = sqrtf(dy * dy + dz * dz);

    _t += (_speed * (dt / 1000.0f)) / edgeLen;

    if (_t >= 1.0f) {
        _t = 1.0f;
        _ctrl.moveTo(FTRI_X, FVERTICES[next].y, FVERTICES[next].z);
        _holding = true;
        _holdStartMs = now;
        return;
    }

    float y = FVERTICES[_edge].y + dy * _t;
    float z = FVERTICES[_edge].z + dz * _t;
    _ctrl.moveTo(FTRI_X, y, z);
}

bool FTriangleGesture::isRunning() { return _running; }
void FTriangleGesture::setSpeed(float speed) { _speed = speed; }
