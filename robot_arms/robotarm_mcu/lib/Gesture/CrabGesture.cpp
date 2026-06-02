/**
 * CrabGesture.cpp — Crab-bites sequence
 *
 * Pattern: The arm tucks into a high retracted pose (shoulder ≈ -60°,
 * elbow ≈ 90°), then lunges forward in a random direction at peak
 * speed while the grip starts closing. On arrival, the grip is
 * force-snapped shut via direct PWM step. Holds briefly, then
 * slowly retracts back. Loops until stop().
 */

#include "CrabGesture.h"

CrabGesture::CrabGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth)
    : _planner(planner), _ctrl(ctrl), _smooth(smooth),
      _running(false), _speed(50.0f), _phase(0), _attackY(0.0f) {
}

void CrabGesture::start() {
    _running = true;
    _phase = 0;
    _attackY = 0.0f;
    _planner.clearQueue();

    // Move to retracted "crab ready" position (shoulder ≈ -60°, elbow ≈ 90°)
    _planner.enqueue(10.0f, 0.0f, 116.0f, GRIP_OPEN_ANGLE, _speed);

    Serial.println("[Gesture] Crab bites started");
}

void CrabGesture::stop() {
    _running = false;
    _planner.clearQueue();
    // Smooth return to home (1s) instead of instant snap
    _smooth.startTimedMove(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, HOME_GRIP, 1000);
    Serial.println("[Gesture] Crab bites stopped");
}

void CrabGesture::update() {
    if (!_running) return;

    if (_planner.isIdle()) {
        _enqueueNextPhase();
    }
}

bool CrabGesture::isRunning() {
    return _running;
}

void CrabGesture::setSpeed(float speed) {
    _speed = speed;
}

void CrabGesture::_enqueueNextPhase() {
    switch (_phase % 3) {
        case 0: // Lunge forward in random direction, grip starts closing — peak speed
            _attackY = (float)random(-60, 61);
            _planner.enqueue(110.0f, _attackY, 68.0f, GRIP_CLOSED_ANGLE, 500.0f);
            break;
        case 1: // Force grip fully closed (direct PWM step) + hold bite briefly
            _ctrl.setGrip(GRIP_CLOSED_ANGLE);
            _planner.enqueue(112.0f, _attackY, 69.0f, GRIP_CLOSED_ANGLE, 15.0f);
            break;
        case 2: // Retract + open grip, back to center — slow
            _planner.enqueue(10.0f, 0.0f, 116.0f, GRIP_OPEN_ANGLE, _speed * 0.4f);
            break;
    }

    _phase++;
}
