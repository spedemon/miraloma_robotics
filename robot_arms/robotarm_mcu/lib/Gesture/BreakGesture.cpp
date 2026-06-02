/**
 * BreakGesture.cpp — Break dance gesture
 *
 * A 20-keyframe loop that simulates breakdance moves:
 *   - Toprock: snappy side-to-side groove
 *   - Drop & Sweep: explosive drop to low, wide floor sweeps
 *   - Freeze: dramatic back-lean pose with long hold
 *   - Windmill: continuous circular power sweep
 *   - Mirror Freeze: opposite-side freeze
 *
 * Loops until stop(), then returns home.
 *
 * Workspace reference (L1=40, L2=86, d0=22):
 *   Home:  X≈0, Y=0, Z=148       Max reach ≈ 126 mm
 *   Back-lean (freeze):  X=-5, Z=138-140  →  negative shoulder servo
 *   Floor sweep:         X=95, Z=28       →  large positive elbow servo
 */

#include "BreakGesture.h"

// Break keyframe: {X, Y, Z, speed_multiplier}
struct BreakKey {
    float x, y, z, speedMul;
};

static const BreakKey BREAK_KEYS[] = {
    // --- Section 1: Toprock (standing groove) ---
    {  40.0f, -45.0f,  95.0f, 1.4f },  //  0: SNAP right
    {  40.0f, -45.0f,  95.0f, 0.1f },  //  1: hold beat
    {  40.0f,  45.0f,  95.0f, 1.4f },  //  2: SNAP left
    {  40.0f,  45.0f,  95.0f, 0.1f },  //  3: hold beat

    // --- Section 2: Drop & Floor Sweep ---
    {  80.0f,   0.0f,  35.0f, 1.6f },  //  4: explosive drop
    {  95.0f, -55.0f,  28.0f, 1.2f },  //  5: low sweep right
    {  95.0f,  55.0f,  28.0f, 1.0f },  //  6: low sweep left (wide arc)
    {  95.0f, -55.0f,  28.0f, 1.2f },  //  7: low sweep back right

    // --- Section 3: Freeze ---
    {  -5.0f,  35.0f, 140.0f, 1.6f },  //  8: SNAP to freeze pose
    {  -5.0f,  35.0f, 140.0f, 0.05f},  //  9: HOLD freeze
    {  15.0f,   0.0f, 145.0f, 1.0f },  // 10: release to center tall

    // --- Section 4: Windmill (circular power sweep) ---
    {  30.0f, -55.0f, 120.0f, 1.4f },  // 11: sweep up-right
    {  90.0f, -20.0f,  35.0f, 1.3f },  // 12: sweep forward-low
    {  60.0f,  50.0f,  80.0f, 1.3f },  // 13: sweep left-mid
    {  20.0f,  40.0f, 135.0f, 1.3f },  // 14: sweep up-left
    {  10.0f,   0.0f, 145.0f, 1.3f },  // 15: sweep back-center-tall
    {  70.0f, -40.0f,  50.0f, 1.4f },  // 16: sweep down-right

    // --- Section 5: Mirror Freeze ---
    {  -5.0f, -40.0f, 138.0f, 1.6f },  // 17: SNAP to mirror freeze
    {  -5.0f, -40.0f, 138.0f, 0.05f},  // 18: HOLD freeze
    {  15.0f,   0.0f, 145.0f, 1.0f },  // 19: release to center tall
};
static const int BREAK_KEY_COUNT = sizeof(BREAK_KEYS) / sizeof(BREAK_KEYS[0]);

BreakGesture::BreakGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(80.0f), _phase(0) {
}

void BreakGesture::start() {
    _running = true;
    _phase = 0;
    _planner.clearQueue();
    _enqueueNextPhase();
    Serial.println("[Gesture] Break started");
}

void BreakGesture::stop() {
    _running = false;
    _planner.clearQueue();
    _ctrl.home();
    Serial.println("[Gesture] Break stopped");
}

void BreakGesture::update() {
    if (!_running) return;

    if (_planner.isIdle()) {
        _enqueueNextPhase();
    }
}

bool BreakGesture::isRunning() {
    return _running;
}

void BreakGesture::setSpeed(float speed) {
    _speed = speed;
}

void BreakGesture::_enqueueNextPhase() {
    float grip = _ctrl.getGrip();

    // Batch-enqueue 4 keyframes at a time for continuous flow.
    for (int i = 0; i < 4; i++) {
        const BreakKey& k = BREAK_KEYS[_phase % BREAK_KEY_COUNT];
        _planner.enqueue(k.x, k.y, k.z, grip, _speed * k.speedMul);
        _phase++;
    }
}
