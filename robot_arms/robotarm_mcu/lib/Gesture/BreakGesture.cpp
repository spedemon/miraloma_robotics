/**
 * BreakGesture.cpp — 50-keyframe data-driven break dance
 *
 * A looping sequence of explosive, dramatic joint-space moves.
 * Patterns inspired by the Animation Maker export (last 12 fast keyframes):
 *   - Toprock: snappy standing groove
 *   - Power drops: explosive drops to floor
 *   - Freezes: dramatic held poses
 *   - Windmills: circular full-range sweeps
 *   - Power moves: rapid direction reversals
 *   - Grand finale: maximum range explosions
 *
 * Uses extreme joint angles and fast/varied timing (400–1000ms)
 * for an aggressive, breakdance feel.
 *
 * Joint limits: base ±90°, shoulder -109..+104°, elbow ±100°, grip ±90°
 */

#include "BreakGesture.h"

// Joint-space keyframe: {base, shoulder, elbow, grip, durationMs}
struct BreakKey {
    float    base;
    float    shoulder;
    float    elbow;
    float    grip;
    uint16_t durationMs;
};

// 50 keyframes — explosive, dramatic break dance loop
static const BreakKey BREAK_KEYS[] PROGMEM = {
    // === Section 1: Toprock (snappy standing groove, 8 keyframes) ===
    {   0.0f,    0.0f,    0.0f,   0.0f,  800 },  //  0: start from home
    {  79.0f,    0.0f,    0.0f,   0.0f,  700 },  //  1: whip right
    {  79.0f,    0.0f,  -98.0f,   0.0f,  600 },  //  2: arm snap back
    { -79.0f,    0.0f,  -98.0f,   0.0f,  600 },  //  3: cross to left
    { -79.0f,    0.0f,   50.0f,   0.0f,  700 },  //  4: arm forward
    {   0.0f,  -20.0f,   70.0f,   0.0f,  800 },  //  5: center recover
    {  40.0f,   25.0f,  -40.0f,   0.0f,  600 },  //  6: right punch
    { -40.0f,   25.0f,  -40.0f,   0.0f,  600 },  //  7: left punch

    // === Section 2: Power Drop & Floor Sweep (8 keyframes) ===
    {   0.0f,   90.0f,  -90.0f,   0.0f,  500 },  //  8: explosive drop
    {  60.0f,   85.0f,  -80.0f,   0.0f,  700 },  //  9: floor sweep right
    { -60.0f,   85.0f,  -80.0f,   0.0f,  800 },  // 10: floor sweep left (wide arc)
    {  70.0f,   80.0f,  -85.0f,   0.0f,  700 },  // 11: sweep back right
    { -70.0f,   80.0f,  -85.0f,   0.0f,  700 },  // 12: sweep back left
    {   0.0f,   95.0f,  -95.0f,   0.0f,  500 },  // 13: center slam
    {   0.0f,   50.0f,  -50.0f,   0.0f,  600 },  // 14: partial rise
    {   0.0f,    0.0f,    0.0f,   0.0f,  700 },  // 15: full stand

    // === Section 3: Freeze #1 — Back Lean (6 keyframes) ===
    {  80.0f, -100.0f,   90.0f,  20.0f,  500 },  // 16: SNAP to freeze right
    {  80.0f, -100.0f,   90.0f,  20.0f,  900 },  // 17: HOLD freeze
    {   0.0f,  -50.0f,   45.0f,   0.0f,  600 },  // 18: release
    { -80.0f, -100.0f,   90.0f,  20.0f,  500 },  // 19: SNAP to freeze left
    { -80.0f, -100.0f,   90.0f,  20.0f,  900 },  // 20: HOLD freeze
    {   0.0f,    0.0f,    0.0f,   0.0f,  600 },  // 21: release to home

    // === Section 4: Windmill (circular power sweep, 10 keyframes) ===
    {  85.0f,  100.0f,  -98.0f,   0.0f,  600 },  // 22: full reach right-forward
    { -85.0f, -105.0f,   99.0f,   0.0f,  700 },  // 23: full reach left-back
    {  85.0f,  100.0f,  -98.0f,   0.0f,  600 },  // 24: reverse right
    {  85.0f,    0.0f,  -93.0f,   0.0f,  500 },  // 25: horizontal right
    { -88.0f,    0.0f,  -93.0f,   0.0f,  500 },  // 26: whip to left
    {  88.0f,    0.0f,  -93.0f,   0.0f,  500 },  // 27: whip back right
    { -85.0f,   -3.0f,   -1.0f,   0.0f,  450 },  // 28: left neutral snap
    {  85.0f,   -3.0f,   -1.0f,   0.0f,  450 },  // 29: right neutral snap
    {   0.0f,  -50.0f,   80.0f,   0.0f,  600 },  // 30: back lean center
    {   0.0f,    0.0f,    0.0f,   0.0f,  700 },  // 31: home reset

    // === Section 5: Power Moves (rapid reversals, 10 keyframes) ===
    {  90.0f, -100.0f,   89.0f,   0.0f,  500 },  // 32: extreme right-back
    {  90.0f,   88.0f,  -91.0f,   0.0f,  500 },  // 33: snap forward
    {  90.0f,   88.0f,   31.0f,   0.0f,  600 },  // 34: elbow fold
    { -90.0f,  -99.0f,  -25.0f,   0.0f,  500 },  // 35: cross to left extreme
    { -45.0f,  -99.0f,  -25.0f,   0.0f,  600 },  // 36: partial right shift
    {  45.0f,   80.0f,  -70.0f,  15.0f,  500 },  // 37: power reach right
    { -45.0f,   80.0f,  -70.0f,  15.0f,  500 },  // 38: power reach left
    {   0.0f, -105.0f,   95.0f,  25.0f,  600 },  // 39: max back lean + grip
    {   0.0f,  100.0f,  -98.0f,   0.0f,  500 },  // 40: max forward slam
    {   0.0f,    0.0f,    0.0f,   0.0f,  700 },  // 41: home reset

    // === Section 6: Grand Finale (explosive combos, 8 keyframes) ===
    {  85.0f, -102.0f,   72.0f,  20.0f,  500 },  // 42: dramatic lean right
    { -85.0f, -102.0f,   72.0f,  20.0f,  500 },  // 43: mirror lean left
    {   0.0f,  100.0f,  -98.0f,   0.0f,  450 },  // 44: forward explosion
    {   0.0f, -105.0f,   99.0f,   0.0f,  450 },  // 45: backward explosion
    {  90.0f,    0.0f,  -95.0f,   0.0f,  400 },  // 46: right whip
    { -90.0f,    0.0f,  -95.0f,   0.0f,  400 },  // 47: left whip
    {   0.0f, -105.0f,   -5.0f,  20.0f,  600 },  // 48: back lean arms tight
    {   0.0f,    0.0f,    0.0f,   0.0f,  800 },  // 49: home (loop reset)
};
static const int BREAK_KEY_COUNT = sizeof(BREAK_KEYS) / sizeof(BREAK_KEYS[0]);

BreakGesture::BreakGesture(ArmController& ctrl, SmoothMover& smooth)
    : _ctrl(ctrl), _smooth(smooth),
      _running(false), _timeScale(1.0f), _phase(0) {
}

void BreakGesture::start() {
    _running = true;
    _phase = 0;
    _smooth.stopAll();
    _enqueueNextKeyframe();
    Serial.println("[Gesture] Break started");
}

void BreakGesture::stop() {
    _running = false;
    _smooth.stopAll();
    _ctrl.home();
    Serial.println("[Gesture] Break stopped");
}

void BreakGesture::update() {
    if (!_running) return;

    // When the SmoothMover finishes the current keyframe, advance
    if (!_smooth.isBusy()) {
        _enqueueNextKeyframe();
    }
}

bool BreakGesture::isRunning() {
    return _running;
}

void BreakGesture::setSpeed(float speed) {
    // Convert speed (mm/s conceptually) to a time-scale:
    //   speed=80 → scale=1.0 (default)
    //   speed=160 → scale=2.0 (twice as fast)
    //   speed=40 → scale=0.5 (half speed)
    if (speed > 0.0f) {
        _timeScale = speed / 80.0f;
    }
}

void BreakGesture::_enqueueNextKeyframe() {
    const BreakKey& k = BREAK_KEYS[_phase % BREAK_KEY_COUNT];

    // Scale duration by time factor (faster timeScale = shorter duration)
    uint32_t duration = (uint32_t)(k.durationMs / _timeScale);
    if (duration < 50) duration = 50;  // Minimum duration guard

    _smooth.startTimedMove(k.base, k.shoulder, k.elbow, k.grip, duration);
    _phase++;
}
