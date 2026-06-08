/**
 * FSquareGesture.cpp — Smooth front-facing square via edge-walking
 *
 * YZ plane at X=90. Center (Y=-2, Z=58), side≈62.5mm.
 * Rotated -30° from frontal.
 */

#include "FSquareGesture.h"

static const float FSQ_X = 90.0f;
static const uint32_t CORNER_HOLD_MS = 200;
static const float ROT_ANGLE = -M_PI / 6.0f;  // -30° rotation

struct FVec2 { float y, z; };
static const FVec2 FCORNERS[] = {
    {  29.3f, 89.3f },  // 0: top-right
    { -33.3f, 89.3f },  // 1: top-left
    { -33.3f, 26.7f },  // 2: bottom-left
    {  29.3f, 26.7f },  // 3: bottom-right
};

FSquareGesture::FSquareGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth)
    : _planner(planner), _ctrl(ctrl), _smooth(smooth),
      _running(false), _speed(75.0f),
      _edge(0), _t(0.0f), _lastTickMs(0), _holdStartMs(0), _holding(false) {
}

void FSquareGesture::start() {
    _running = true;
    _planner.clearQueue();
    _edge = 0; _t = 0.0f; _holding = false;
    _lastTickMs = millis();

    // Smooth lead-in: travel to the first corner
    float startY = FCORNERS[0].y;
    float rotX = FSQ_X * cosf(ROT_ANGLE) - startY * sinf(ROT_ANGLE);
    float rotY = FSQ_X * sinf(ROT_ANGLE) + startY * cosf(ROT_ANGLE);
    _planner.enqueue(rotX, rotY, FCORNERS[0].z, _ctrl.getGrip(), _speed);
    _leadIn = true;

    Serial.println("[Gesture] FSquare started");
}

void FSquareGesture::stop() {
    _running = false;
    // Smooth return to home (1s) instead of instant snap
    _smooth.startTimedMove(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, HOME_GRIP, 1000);
    Serial.println("[Gesture] FSquare stopped");
}

void FSquareGesture::update() {
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
        if (now - _holdStartMs >= CORNER_HOLD_MS) {
            _holding = false;
            _edge = (_edge + 1) % 4;
            _t = 0.0f;
        }
        return;
    }

    uint8_t next = (_edge + 1) % 4;
    float dy = FCORNERS[next].y - FCORNERS[_edge].y;
    float dz = FCORNERS[next].z - FCORNERS[_edge].z;
    float edgeLen = sqrtf(dy * dy + dz * dz);

    _t += (_speed * (dt / 1000.0f)) / edgeLen;

    if (_t >= 1.0f) {
        _t = 1.0f;
        float nextY = FCORNERS[next].y;
        float rotX = FSQ_X * cosf(ROT_ANGLE) - nextY * sinf(ROT_ANGLE);
        float rotY = FSQ_X * sinf(ROT_ANGLE) + nextY * cosf(ROT_ANGLE);
        _ctrl.moveTo(rotX, rotY, FCORNERS[next].z);
        _holding = true;
        _holdStartMs = now;
        return;
    }

    float y = FCORNERS[_edge].y + dy * _t;
    float z = FCORNERS[_edge].z + dz * _t;
    float rotX = FSQ_X * cosf(ROT_ANGLE) - y * sinf(ROT_ANGLE);
    float rotY = FSQ_X * sinf(ROT_ANGLE) + y * cosf(ROT_ANGLE);
    _ctrl.moveTo(rotX, rotY, z);
}

bool FSquareGesture::isRunning() { return _running; }
void FSquareGesture::setSpeed(float speed) { _speed = speed; }
