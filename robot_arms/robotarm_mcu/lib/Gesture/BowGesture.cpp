/**
 * BowGesture.cpp — Elbow-hinge bow sequence
 *
 * The arm bows 4 times facing different directions, like a person
 * bowing at the hip to greet a surrounding crowd.
 *
 * Motion is purely joint-space via SmoothMover:
 *   1. Rotate base to face a direction
 *   2. Bend elbow down (the "bow")
 *   3. Brief hold at bottom
 *   4. Straighten elbow back up
 *   5. Repeat for next direction
 *   6. Return home
 *
 * Shoulder stays fixed at home — only the elbow hinges.
 */

#include "BowGesture.h"

// --- Tuning constants ---

// Base servo angles for the 4 bow directions (degrees).
// 0 = forward, negative = right, positive = left.
const float BowGesture::BASE_ANGLES[BOW_COUNT] = {
    0.0f,     // Forward
   -45.0f,    // Right
    45.0f,    // Left
    0.0f      // Forward again
};

// Elbow servo angle at the deepest point of the bow (degrees).
// Home elbow is 0°; positive values bend the forearm forward/down.
const float BowGesture::ELBOW_BOW_ANGLE = 70.0f;

// How long to pause at the bottom of each bow (ms).
const uint32_t BowGesture::HOLD_DURATION_MS = 300;

// ---------------------------------------------------------------------------

BowGesture::BowGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth)
    : _planner(planner), _ctrl(ctrl), _smooth(smooth),
      _running(false), _phase(DONE), _bowIndex(0), _holdStartMs(0) {
}

void BowGesture::start() {
    _running = true;
    _bowIndex = 0;
    _planner.clearQueue();
    _smooth.stopAll();

    // Start by rotating to the first base angle
    _phase = ROTATE_BASE;
    _smooth.startMove(SERVO_CH_BASE, BASE_ANGLES[0]);

    Serial.println("[Gesture] Bow started");
}

void BowGesture::stop() {
    _running = false;
    _smooth.stopAll();
    _planner.clearQueue();
    _ctrl.home();
    Serial.println("[Gesture] Bow stopped");
}

void BowGesture::update() {
    if (!_running) return;

    switch (_phase) {

    case ROTATE_BASE:
        // Wait for the base rotation to finish
        if (!_smooth.isJointBusy(SERVO_CH_BASE)) {
            // Base is in position — start bending the elbow down
            _phase = BOW_DOWN;
            _smooth.startMove(SERVO_CH_ELBOW, ELBOW_BOW_ANGLE);
        }
        break;

    case BOW_DOWN:
        // Wait for the elbow to reach the bowed position
        if (!_smooth.isJointBusy(SERVO_CH_ELBOW)) {
            // Hold briefly at the bottom
            _phase = HOLD;
            _holdStartMs = millis();
        }
        break;

    case HOLD:
        // Pause at the bottom of the bow
        if (millis() - _holdStartMs >= HOLD_DURATION_MS) {
            // Rise back up — return elbow to home
            _phase = BOW_UP;
            _smooth.startMove(SERVO_CH_ELBOW, HOME_ELBOW);
        }
        break;

    case BOW_UP:
        // Wait for the elbow to straighten
        if (!_smooth.isJointBusy(SERVO_CH_ELBOW)) {
            _bowIndex++;
            if (_bowIndex < BOW_COUNT) {
                // Rotate to the next direction, then bow again
                _phase = ROTATE_BASE;
                _smooth.startMove(SERVO_CH_BASE, BASE_ANGLES[_bowIndex]);
            } else {
                // All bows complete — return home
                _phase = RETURN_HOME;
                _smooth.startMove(SERVO_CH_BASE, HOME_BASE);
                _smooth.startMove(SERVO_CH_ELBOW, HOME_ELBOW);
                _smooth.startMove(SERVO_CH_SHOULDER, HOME_SHOULDER);
            }
        }
        break;

    case RETURN_HOME:
        // Wait for all joints to reach home
        if (!_smooth.isBusy()) {
            _phase = DONE;
            _running = false;
            Serial.println("[Gesture] Bow complete");
        }
        break;

    case DONE:
        _running = false;
        break;
    }
}

bool BowGesture::isRunning() {
    return _running;
}
