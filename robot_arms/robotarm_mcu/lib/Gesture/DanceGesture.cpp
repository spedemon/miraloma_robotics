/**
 * DanceGesture.cpp — Beat-driven modern flow dance
 *
 * A 16-keyframe beat pattern: fast SNAPS with brief holds, interspersed
 * with flowing sweeps.  Uses the arm's full range including backward-
 * leaning positions (negative shoulder/elbow servo angles) and low
 * forward dips.  Loops until stop(), then returns home.
 *
 * Workspace reference (L1=40, L2=86, d0=22):
 *   Home:  X≈0, Y=0, Z=148       Max reach ≈ 126 mm
 *   Backward lean:  X < 10, Z > 130  →  negative shoulder servo
 *   Forward dip:    X > 80, Z < 40   →  large positive elbow servo
 */

#include "DanceGesture.h"

// Dance keyframe: {X, Y, Z, speed_multiplier}
struct DanceKey {
    float x, y, z, speedMul;
};

// 16-keyframe beat-driven loop.
// Pattern: SNAP(fast) → hold → SNAP → hold → FLOW → FLOW → ...
static const DanceKey DANCE_KEYS[] = {
    // --- Beat 1: snappy side-to-side at mid height ---
    {  40.0f, -50.0f, 100.0f, 1.6f },  //  0: SNAP right
    {  40.0f, -50.0f, 100.0f, 0.1f },  //  1: hold beat
    {  40.0f,  50.0f, 100.0f, 1.6f },  //  2: SNAP left
    {  40.0f,  50.0f, 100.0f, 0.1f },  //  3: hold beat

    // --- Flow: sweep down to forward dip ---
    {  85.0f, -30.0f,  40.0f, 1.0f },  //  4: sweep down-right
    {  95.0f,  20.0f,  30.0f, 1.0f },  //  5: forward low dip

    // --- Beat 2: snappy back-lean (negative shoulder!) ---
    {  -5.0f,  40.0f, 138.0f, 1.6f },  //  6: SNAP back-left (neg shoulder)
    {  -5.0f,  40.0f, 138.0f, 0.1f },  //  7: hold beat
    {  -5.0f, -40.0f, 138.0f, 1.6f },  //  8: SNAP back-right (neg shoulder)
    {  -5.0f, -40.0f, 138.0f, 0.1f },  //  9: hold beat

    // --- Flow: low sweep ---
    {  80.0f,   0.0f,  45.0f, 1.1f },  // 10: low forward center
    {  50.0f,  55.0f,  75.0f, 1.1f },  // 11: sweep left-mid

    // --- Beat 3: high snappy punches ---
    {  10.0f, -35.0f, 142.0f, 1.6f },  // 12: SNAP up-right (neg shoulder)
    {  10.0f, -35.0f, 142.0f, 0.1f },  // 13: hold beat
    {  10.0f,  35.0f, 142.0f, 1.6f },  // 14: SNAP up-left (neg shoulder)
    {  10.0f,  35.0f, 142.0f, 0.1f },  // 15: hold beat
};
static const int DANCE_KEY_COUNT = sizeof(DANCE_KEYS) / sizeof(DANCE_KEYS[0]);

DanceGesture::DanceGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(80.0f), _phase(0) {
}

void DanceGesture::start() {
    _running = true;
    _phase = 0;
    _planner.clearQueue();
    _enqueueNextPhase();
    Serial.println("[Gesture] Dance started");
}

void DanceGesture::stop() {
    _running = false;
    _planner.clearQueue();
    _ctrl.home();
    Serial.println("[Gesture] Dance stopped");
}

void DanceGesture::update() {
    if (!_running) return;

    // When the planner is idle, enqueue the next batch of keyframes
    if (_planner.isIdle()) {
        _enqueueNextPhase();
    }
}

bool DanceGesture::isRunning() {
    return _running;
}

void DanceGesture::setSpeed(float speed) {
    _speed = speed;
}

void DanceGesture::_enqueueNextPhase() {
    float grip = _ctrl.getGrip();

    // Batch-enqueue 4 keyframes at a time for continuous flow.
    for (int i = 0; i < 4; i++) {
        const DanceKey& k = DANCE_KEYS[_phase % DANCE_KEY_COUNT];
        _planner.enqueue(k.x, k.y, k.z, grip, _speed * k.speedMul);
        _phase++;
    }
}
