/**
 * FTriangleGesture.cpp — Smooth front-facing triangle via edge-walking
 *
 * YZ plane at X=90. Center (Y=-2, Z=58), R=44mm, equilateral.
 * Rotated -30° from frontal.
 */

#include "FTriangleGesture.h"

static const float FTRI_X = 90.0f;
static const uint32_t VERTEX_HOLD_MS = 200;
static const float ROT_ANGLE = -M_PI / 6.0f;  // -30° rotation

struct FVec2 { float y, z; };
static const FVec2 FVERTICES[] = {
    {  -2.0f, 102.2f },  // 0: top
    { -40.3f,  35.9f },  // 1: bottom-left
    {  36.3f,  35.9f },  // 2: bottom-right
};

FTriangleGesture::FTriangleGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth)
    : _planner(planner), _ctrl(ctrl), _smooth(smooth),
      _running(false), _speed(75.0f),
      _edge(0), _t(0.0f), _lastTickMs(0), _holdStartMs(0), _holding(false) {
}

void FTriangleGesture::start() {
    _running = true;
    _planner.clearQueue();
    _edge = 0; _t = 0.0f; _holding = false;
    _lastTickMs = millis();

    // Smooth lead-in: travel to the first vertex
    float startY = FVERTICES[0].y;
    float rotX = FTRI_X * cosf(ROT_ANGLE) - startY * sinf(ROT_ANGLE);
    float rotY = FTRI_X * sinf(ROT_ANGLE) + startY * cosf(ROT_ANGLE);
    _planner.enqueue(rotX, rotY, FVERTICES[0].z, _ctrl.getGrip(), _speed);
    _leadIn = true;

    Serial.println("[Gesture] FTriangle started");
}

void FTriangleGesture::stop() {
    _running = false;
    // Smooth return to home (1s) instead of instant snap
    _smooth.startTimedMove(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, HOME_GRIP, 1000);
    Serial.println("[Gesture] FTriangle stopped");
}

void FTriangleGesture::update() {
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
    float dy = FVERTICES[next].y - FVERTICES[_edge].y;
    float dz = FVERTICES[next].z - FVERTICES[_edge].z;
    float edgeLen = sqrtf(dy * dy + dz * dz);

    _t += (_speed * (dt / 1000.0f)) / edgeLen;

    if (_t >= 1.0f) {
        _t = 1.0f;
        float nextY = FVERTICES[next].y;
        float rotX = FTRI_X * cosf(ROT_ANGLE) - nextY * sinf(ROT_ANGLE);
        float rotY = FTRI_X * sinf(ROT_ANGLE) + nextY * cosf(ROT_ANGLE);
        _ctrl.moveTo(rotX, rotY, FVERTICES[next].z);
        _holding = true;
        _holdStartMs = now;
        return;
    }

    float y = FVERTICES[_edge].y + dy * _t;
    float z = FVERTICES[_edge].z + dz * _t;
    float rotX = FTRI_X * cosf(ROT_ANGLE) - y * sinf(ROT_ANGLE);
    float rotY = FTRI_X * sinf(ROT_ANGLE) + y * cosf(ROT_ANGLE);
    _ctrl.moveTo(rotX, rotY, z);
}

bool FTriangleGesture::isRunning() { return _running; }
void FTriangleGesture::setSpeed(float speed) { _speed = speed; }
