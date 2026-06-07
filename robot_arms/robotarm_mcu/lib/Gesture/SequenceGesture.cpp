#include "SequenceGesture.h"

SequenceGesture::SequenceGesture(SmoothMover& smooth)
    : _smooth(smooth), _running(false), _phase(0), _keyframeCount(0) {
}

void SequenceGesture::clear() {
    _keyframeCount = 0;
}

bool SequenceGesture::addKeyframe(float base, float shoulder, float elbow, float grip, uint32_t durationMs) {
    if (_keyframeCount >= MAX_KEYFRAMES) return false;
    _keyframes[_keyframeCount++] = {base, shoulder, elbow, grip, durationMs};
    return true;
}

void SequenceGesture::start() {
    if (_keyframeCount == 0) {
        _running = false;
        return;
    }
    _running = true;
    _phase = 0;
    _smooth.stopAll();
    _enqueueNextKeyframe();
    Serial.println("[Gesture] Custom sequence started");
}

void SequenceGesture::stop() {
    _running = false;
    _smooth.stopAll();
    _smooth.startTimedMove(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, HOME_GRIP, 1000);
    Serial.println("[Gesture] Custom sequence stopped");
}

void SequenceGesture::update() {
    if (!_running) return;
    if (!_smooth.isBusy()) {
        _enqueueNextKeyframe();
    }
}

bool SequenceGesture::isRunning() {
    return _running;
}

void SequenceGesture::_enqueueNextKeyframe() {
    if (_keyframeCount == 0) return;
    const SequenceKeyframe& k = _keyframes[_phase % _keyframeCount];
    _smooth.startTimedMove(k.base, k.shoulder, k.elbow, k.grip, k.durationMs);
    _phase++;
}
