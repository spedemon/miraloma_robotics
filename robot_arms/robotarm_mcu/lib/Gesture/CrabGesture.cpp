/**
 * CrabGesture.cpp — Crab-bites sequence
 *
 * Pattern: The arm holds a horizontal position with the grip acting
 * like a claw. It lunges forward while closing the grip (bite),
 * then retracts while opening the grip. Loops until stop().
 *
 * The arm stays low and horizontal to look like a crab claw.
 */

#include "CrabGesture.h"

CrabGesture::CrabGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(50.0f), _phase(0) {
}

void CrabGesture::start() {
    _running = true;
    _phase = 0;
    _planner.clearQueue();

    // Move to starting "crab ready" position: low, forward, grip open
    _planner.enqueue(70.0f, 0.0f, 30.0f, GRIP_OPEN_ANGLE, _speed);

    Serial.println("[Gesture] Crab bites started");
}

void CrabGesture::stop() {
    _running = false;
    _planner.clearQueue();
    _ctrl.home();
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
    switch (_phase % 4) {
        case 0: // Lunge forward + close grip (BITE!)
            _planner.enqueue(110.0f, 0.0f, 28.0f, GRIP_CLOSED_ANGLE, _speed);
            break;
        case 1: // Hold bite briefly (tiny move)
            _planner.enqueue(110.0f, 0.0f, 32.0f, GRIP_CLOSED_ANGLE, 15.0f);
            break;
        case 2: // Retract + open grip
            _planner.enqueue(60.0f, 0.0f, 35.0f, GRIP_OPEN_ANGLE, _speed * 0.7f);
            break;
        case 3: // Reset to ready position
            _planner.enqueue(70.0f, 0.0f, 30.0f, GRIP_OPEN_ANGLE, _speed * 0.5f);
            break;
    }

    _phase++;
}
