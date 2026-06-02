/**
 * FSquareGesture.cpp — Smooth front-facing square via edge-walking
 *
 * YZ plane at X=90. Center (Y=-2, Z=58), side≈62.5mm.
 */

#include "FSquareGesture.h"

static const float FSQ_X = 90.0f;
static const uint32_t CORNER_HOLD_MS = 200;

struct FVec2 { float y, z; };
static const FVec2 FCORNERS[] = {
    {  29.3f, 89.3f },  // 0: top-right
    { -33.3f, 89.3f },  // 1: top-left
    { -33.3f, 26.7f },  // 2: bottom-left
    {  29.3f, 26.7f },  // 3: bottom-right
};

FSquareGesture::FSquareGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(75.0f),
      _edge(0), _t(0.0f), _lastTickMs(0), _holdStartMs(0), _holding(false) {
}

void FSquareGesture::start() {
    _running = true;
    _planner.clearQueue();
    _edge = 0; _t = 0.0f; _holding = false;
    _lastTickMs = millis();
    Serial.println("[Gesture] FSquare started");
}

void FSquareGesture::stop() {
    _running = false;
    _ctrl.home();
    Serial.println("[Gesture] FSquare stopped");
}

void FSquareGesture::update() {
    if (!_running) return;

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
        _ctrl.moveTo(FSQ_X, FCORNERS[next].y, FCORNERS[next].z);
        _holding = true;
        _holdStartMs = now;
        return;
    }

    float y = FCORNERS[_edge].y + dy * _t;
    float z = FCORNERS[_edge].z + dz * _t;
    _ctrl.moveTo(FSQ_X, y, z);
}

bool FSquareGesture::isRunning() { return _running; }
void FSquareGesture::setSpeed(float speed) { _speed = speed; }
