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
 * Grip choreography (4th degree of freedom):
 *   - Toprock: sharp fist-pump snaps, open on whips, clench on punches
 *   - Power drops: slam shut on impact, hold clenched through floor sweeps
 *   - Freezes: max clench for dramatic held poses, release on transitions
 *   - Windmills: wide open for momentum/flair, snap shut on direction changes
 *   - Power wave: rapid flutter alternating open/closed for aggressive energy
 *   - Grand finale: full-range dramatic grips, open on explosions, locked on leans
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
// Grip choreography: -30° = fully open, 45° = fully closed, 0° = neutral
static const BreakKey BREAK_KEYS[] PROGMEM = {
    // === Section 1: Toprock (sharp fist-pump snaps) ===
    {   0.0f,    0.0f,    0.0f,  45.0f,  800 },  //  0: start from home, fist clenched
    {  79.0f,    0.0f,    0.0f, -20.0f,  700 },  //  1: whip right, grip flings open
    {  79.0f,    0.0f,  -98.0f,  40.0f,  600 },  //  2: arm snap back, grip punches shut
    { -79.0f,    0.0f,  -98.0f, -25.0f,  600 },  //  3: cross to left, grip whips open
    { -79.0f,    0.0f,   50.0f,  40.0f,  700 },  //  4: arm forward, grip clenches
    {   0.0f,  -20.0f,   70.0f,   0.0f,  800 },  //  5: center recover, grip relaxes
    {  40.0f,   25.0f,  -40.0f,  45.0f,  600 },  //  6: right punch, fist tight
    { -40.0f,   25.0f,  -40.0f,  45.0f,  600 },  //  7: left punch, fist tight

    // === Section 2: Power Drop & Floor Sweep (slam on impact, hold through sweeps) ===
    {   0.0f,   90.0f,  -90.0f,  45.0f,  500 },  //  8: explosive drop, grip slams shut
    {  60.0f,   85.0f,  -80.0f,  40.0f,  700 },  //  9: floor sweep right, grip clenched
    { -60.0f,   85.0f,  -80.0f,  40.0f,  800 },  // 10: floor sweep left, grip clenched
    {  70.0f,   80.0f,  -85.0f,  35.0f,  700 },  // 11: sweep back right, grip tight
    { -70.0f,   80.0f,  -85.0f,  35.0f,  700 },  // 12: sweep back left, grip tight
    {   0.0f,   95.0f,  -95.0f,  45.0f,  500 },  // 13: center slam, grip max clench
    {   0.0f,   50.0f,  -50.0f, -10.0f,  600 },  // 14: partial rise, grip releases
    {   0.0f,    0.0f,    0.0f,   0.0f,  700 },  // 15: full stand, grip neutral

    // === Section 3: Freeze #1 — Back Lean (clench hard on freeze, release on transition) ===
    {  80.0f, -100.0f,   90.0f,  45.0f,  500 },  // 16: SNAP to freeze right, grip locked
    {  80.0f, -100.0f,   90.0f,  45.0f,  900 },  // 17: HOLD freeze, grip stays locked
    {   0.0f,  -50.0f,   45.0f, -15.0f,  600 },  // 18: release, grip opens
    { -80.0f, -100.0f,   90.0f,  45.0f,  500 },  // 19: SNAP to freeze left, grip locked
    { -80.0f, -100.0f,   90.0f,  45.0f,  900 },  // 20: HOLD freeze, grip stays locked
    {   0.0f,    0.0f,    0.0f,   0.0f,  600 },  // 21: release to home, grip neutral

    // === Section 4: Windmill (open wide for flair, snap on direction changes) ===
    {  85.0f,  100.0f,  -98.0f, -30.0f,  600 },  // 22: full reach right-fwd, grip wide open
    { -85.0f, -105.0f,   99.0f,  40.0f,  700 },  // 23: full reach left-back, grip snaps shut
    {  85.0f,  100.0f,  -98.0f, -30.0f,  600 },  // 24: reverse right, grip flings open
    {  85.0f,    0.0f,  -93.0f, -20.0f,  500 },  // 25: horizontal right, grip open
    { -88.0f,    0.0f,  -93.0f,  35.0f,  500 },  // 26: whip to left, grip snaps shut
    {  88.0f,    0.0f,  -93.0f, -20.0f,  500 },  // 27: whip back right, grip flings open
    { -85.0f,   -3.0f,   -1.0f,  40.0f,  450 },  // 28: left neutral snap, grip clench
    {  85.0f,   -3.0f,   -1.0f, -25.0f,  450 },  // 29: right neutral snap, grip whips open
    {   0.0f,  -50.0f,   80.0f,  10.0f,  600 },  // 30: back lean center, grip settles
    {   0.0f,    0.0f,    0.0f,   0.0f,  700 },  // 31: home reset, grip neutral

    // === Section 5: Power Wave (rapid flutter for aggressive energy) ===
    {   0.0f,    0.0f,   25.0f, -15.0f,  450 },  // 32: wave start center, grip opens
    {  20.0f,   17.0f,    8.0f,  30.0f,  400 },  // 33: shoulder peak right, grip snaps shut
    {  40.0f,   10.0f,  -20.0f, -20.0f,  400 },  // 34: elbow dip far right, grip flips open
    {  40.0f,  -10.0f,  -20.0f,  35.0f,  400 },  // 35: shoulder valley right, grip punches shut
    {  20.0f,  -17.0f,    8.0f, -15.0f,  450 },  // 36: rising sweep back, grip opens
    {   0.0f,    0.0f,   25.0f,  25.0f,  400 },  // 37: wave restart center, grip closes
    { -20.0f,   17.0f,    8.0f, -20.0f,  400 },  // 38: shoulder peak left, grip flings open
    { -40.0f,   10.0f,  -20.0f,  35.0f,  400 },  // 39: elbow dip far left, grip snaps shut
    { -40.0f,  -10.0f,  -20.0f, -15.0f,  400 },  // 40: shoulder valley left, grip opens
    {   0.0f,    0.0f,    0.0f,   0.0f,  700 },  // 41: home reset, grip neutral

    // === Section 6: Grand Finale (maximum range dramatic grips) ===
    {  85.0f, -102.0f,   72.0f,  45.0f,  500 },  // 42: dramatic lean right, grip max clench
    { -85.0f, -102.0f,   72.0f,  45.0f,  500 },  // 43: mirror lean left, grip max clench
    {   0.0f,  100.0f,  -98.0f, -30.0f,  450 },  // 44: forward explosion, grip blasts open
    {   0.0f, -105.0f,   99.0f,  45.0f,  450 },  // 45: backward explosion, grip slams shut
    {  90.0f,    0.0f,  -95.0f, -30.0f,  400 },  // 46: right whip, grip wide open
    { -90.0f,    0.0f,  -95.0f, -30.0f,  400 },  // 47: left whip, grip wide open
    {   0.0f, -105.0f,   -5.0f,  45.0f,  600 },  // 48: back lean arms tight, grip locked
    {   0.0f,    0.0f,    0.0f,  45.0f,  800 },  // 49: home (loop reset), grip closed
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
    // Smooth return to home (1s) instead of instant snap
    _smooth.startTimedMove(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, HOME_GRIP, 1000);
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
