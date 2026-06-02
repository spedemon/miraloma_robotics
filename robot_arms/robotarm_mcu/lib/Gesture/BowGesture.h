/**
 * BowGesture.h — One-shot bow/thank-you sequence
 *
 * Simple elbow-hinge bow: rotates to 4 base angles,
 * bending only the elbow at each (like a person bowing at the hip).
 * Uses SmoothMover for joint-space motion.
 */

#ifndef MIRA_BOW_GESTURE_H
#define MIRA_BOW_GESTURE_H

#include "Gesture.h"
#include "SmoothMover.h"

class BowGesture : public Gesture {
public:
    BowGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth);

    const char* name() override { return "bow"; }
    void start() override;
    void stop() override;
    void update() override;
    bool isRunning() override;

private:
    MotionPlanner&  _planner;
    ArmController&  _ctrl;
    SmoothMover&    _smooth;
    bool            _running;

    // State machine
    enum Phase { ROTATE_BASE, BOW_DOWN, HOLD, BOW_UP, RETURN_HOME, DONE };
    Phase    _phase;
    uint8_t  _bowIndex;        // Which of the 4 bows we're on (0–3)
    uint32_t _holdStartMs;     // Timer for hold phase

    static const uint8_t  BOW_COUNT = 4;
    static const float    BASE_ANGLES[BOW_COUNT];   // Servo angles for each direction
    static const float    ELBOW_BOW_ANGLE;           // Elbow angle when bowed
    static const uint32_t HOLD_DURATION_MS;          // Pause at bottom of bow
};

#endif // MIRA_BOW_GESTURE_H
