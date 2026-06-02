/**
 * DanceGesture.cpp — 50-keyframe data-driven dance
 *
 * A looping sequence of smooth, rhythmic joint-space moves.
 * Patterns inspired by the Animation Maker export:
 *   - Arm pumps (shoulder/elbow oscillation)
 *   - Gentle base swaying
 *   - Shoulder rolls and elbow waves
 *   - Figure-8 sweeps
 *   - Rhythmic nodding
 *
 * All moves use moderate joint ranges and uniform-ish timing
 * (800–1200ms) for a flowing, musical feel.
 *
 * Joint limits: base ±90°, shoulder -109..+104°, elbow ±100°, grip ±90°
 */

#include "DanceGesture.h"

// Joint-space keyframe: {base, shoulder, elbow, grip, durationMs}
struct DanceKey {
    float    base;
    float    shoulder;
    float    elbow;
    float    grip;
    uint16_t durationMs;
};

// 50 keyframes — smooth, rhythmic dance loop
static const DanceKey DANCE_KEYS[] PROGMEM = {
    // === Phrase 1: Arm Pump (shoulder/elbow oscillation, base centered) ===
    {   0.0f,  -16.0f,   78.0f,   0.0f, 1000 },  //  0: reach up-back
    {   0.0f,   25.0f,   35.0f,   0.0f, 1000 },  //  1: push forward-low
    {   0.0f,  -16.0f,   78.0f,   0.0f, 1000 },  //  2: reach up-back
    {   0.0f,   25.0f,   35.0f,   0.0f, 1000 },  //  3: push forward-low
    {   0.0f,    0.0f,   50.0f,   0.0f,  900 },  //  4: center transition
    {   0.0f,  -20.0f,   60.0f,   0.0f,  900 },  //  5: slight back-lean

    // === Phrase 2: Side Sway (base moves, arm holds shape) ===
    { -15.0f,   20.0f,   40.0f,   0.0f, 1000 },  //  6: sway right, arm out
    {  15.0f,   20.0f,   40.0f,   0.0f, 1000 },  //  7: sway left, arm out
    { -12.0f,   20.0f,   40.0f,   0.0f, 1000 },  //  8: sway right again
    {  14.0f,   20.0f,   40.0f,   0.0f, 1000 },  //  9: sway left again
    {   0.0f,   15.0f,   45.0f,   0.0f,  800 },  // 10: center reset
    {   0.0f,   -5.0f,   55.0f,   0.0f,  800 },  // 11: slight pull back

    // === Phrase 3: Wave (elbow-driven wave while base rocks) ===
    {  -8.0f,   10.0f,   80.0f,   0.0f, 1000 },  // 12: elbow up, lean right
    {   8.0f,   10.0f,   30.0f,   0.0f, 1000 },  // 13: elbow down, lean left
    { -10.0f,    5.0f,   75.0f,   0.0f, 1000 },  // 14: elbow up, lean right
    {  10.0f,    5.0f,   25.0f,   0.0f, 1000 },  // 15: elbow down, lean left
    {   0.0f,   10.0f,   50.0f,   0.0f,  900 },  // 16: center hold
    {   0.0f,  -10.0f,   65.0f,   0.0f,  900 },  // 17: back lean transition

    // === Phrase 4: Shoulder Roll (shoulder sweeps with base accent) ===
    {   5.0f,  -25.0f,   70.0f,   0.0f, 1100 },  // 18: shoulder back high
    {  -5.0f,   30.0f,   30.0f,   0.0f, 1100 },  // 19: shoulder forward low
    {  10.0f,  -20.0f,   65.0f,   0.0f, 1100 },  // 20: shoulder back
    { -10.0f,   28.0f,   35.0f,   0.0f, 1100 },  // 21: shoulder forward
    {   0.0f,    0.0f,   50.0f,   0.0f,  800 },  // 22: center
    {   0.0f,   15.0f,   40.0f,   0.0f,  800 },  // 23: prepare next phrase

    // === Phrase 5: Nod & Dip (rhythmic vertical bobbing) ===
    {   0.0f,   35.0f,   20.0f,   0.0f, 1000 },  // 24: deep forward nod
    {   0.0f,  -10.0f,   70.0f,   0.0f, 1000 },  // 25: pull back high
    {   0.0f,   40.0f,   15.0f,   0.0f, 1000 },  // 26: deeper nod
    {   0.0f,   -5.0f,   60.0f,   0.0f, 1000 },  // 27: recover
    {  -5.0f,   20.0f,   45.0f,   0.0f,  900 },  // 28: slight right accent
    {   5.0f,   20.0f,   45.0f,   0.0f,  900 },  // 29: slight left accent

    // === Phrase 6: Figure-8 Sweep (coordinated base + shoulder + elbow) ===
    { -18.0f,  -15.0f,   75.0f,   0.0f, 1200 },  // 30: sweep right-back
    {  -5.0f,   25.0f,   30.0f,   0.0f, 1000 },  // 31: through center-low
    {  18.0f,  -15.0f,   75.0f,   0.0f, 1200 },  // 32: sweep left-back
    {   5.0f,   25.0f,   30.0f,   0.0f, 1000 },  // 33: through center-low
    {   0.0f,    0.0f,   50.0f,   0.0f,  800 },  // 34: center reset

    // === Phrase 7: Groove (syncopated pump with base twist) ===
    { -12.0f,  -20.0f,   85.0f,   0.0f,  900 },  // 35: pump up-right
    {  12.0f,   30.0f,   25.0f,   0.0f,  900 },  // 36: pump down-left
    { -14.0f,  -18.0f,   80.0f,   0.0f,  900 },  // 37: pump up-right
    {  14.0f,   28.0f,   28.0f,   0.0f,  900 },  // 38: pump down-left
    {   0.0f,    5.0f,   55.0f,   0.0f,  800 },  // 39: center ease
    {   0.0f,  -15.0f,   70.0f,   0.0f, 1000 },  // 40: back lean hold

    // === Phrase 8: Gentle Flow (wide sweeps, slow exits) ===
    { -20.0f,   10.0f,   60.0f,   0.0f, 1200 },  // 41: wide right
    {  20.0f,   10.0f,   60.0f,   0.0f, 1200 },  // 42: wide left
    { -15.0f,  -10.0f,   70.0f,   0.0f, 1100 },  // 43: right lean-back
    {  15.0f,  -10.0f,   70.0f,   0.0f, 1100 },  // 44: left lean-back
    {   0.0f,   20.0f,   35.0f,   0.0f, 1000 },  // 45: forward dip
    {   0.0f,  -15.0f,   65.0f,   0.0f, 1000 },  // 46: back recover
    {   0.0f,   10.0f,   50.0f,   0.0f,  900 },  // 47: center ease
    {   0.0f,   -5.0f,   55.0f,   0.0f,  900 },  // 48: slight back
    {   0.0f,    0.0f,    0.0f,   0.0f, 1000 },  // 49: home (loop reset)
};
static const int DANCE_KEY_COUNT = sizeof(DANCE_KEYS) / sizeof(DANCE_KEYS[0]);

DanceGesture::DanceGesture(ArmController& ctrl, SmoothMover& smooth)
    : _ctrl(ctrl), _smooth(smooth),
      _running(false), _timeScale(1.0f), _phase(0) {
}

void DanceGesture::start() {
    _running = true;
    _phase = 0;
    _smooth.stopAll();
    _enqueueNextKeyframe();
    Serial.println("[Gesture] Dance started");
}

void DanceGesture::stop() {
    _running = false;
    _smooth.stopAll();
    _ctrl.home();
    Serial.println("[Gesture] Dance stopped");
}

void DanceGesture::update() {
    if (!_running) return;

    // When the SmoothMover finishes the current keyframe, advance
    if (!_smooth.isBusy()) {
        _enqueueNextKeyframe();
    }
}

bool DanceGesture::isRunning() {
    return _running;
}

void DanceGesture::setSpeed(float speed) {
    // Convert speed (mm/s conceptually) to a time-scale:
    //   speed=80 → scale=1.0 (default)
    //   speed=160 → scale=2.0 (twice as fast)
    //   speed=40 → scale=0.5 (half speed)
    if (speed > 0.0f) {
        _timeScale = speed / 80.0f;
    }
}

void DanceGesture::_enqueueNextKeyframe() {
    const DanceKey& k = DANCE_KEYS[_phase % DANCE_KEY_COUNT];

    // Scale duration by time factor (faster timeScale = shorter duration)
    uint32_t duration = (uint32_t)(k.durationMs / _timeScale);
    if (duration < 50) duration = 50;  // Minimum duration guard

    _smooth.startTimedMove(k.base, k.shoulder, k.elbow, k.grip, duration);
    _phase++;
}
