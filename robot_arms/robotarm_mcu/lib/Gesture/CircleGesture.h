/**
 * CircleGesture.h — Smooth parametric circle
 */
#ifndef MIRA_CIRCLE_GESTURE_H
#define MIRA_CIRCLE_GESTURE_H

#include "Gesture.h"
#include "SmoothMover.h"

class CircleGesture : public Gesture {
public:
    CircleGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth);
    const char* name() override { return "circle"; }
    void start() override;
    void stop() override;
    void update() override;
    bool isRunning() override;
    bool hasSpeed() override { return true; }
    void setSpeed(float speed) override;

private:
    MotionPlanner& _planner;
    ArmController& _ctrl;
    SmoothMover&   _smooth;
    bool     _running;
    float    _speed;
    uint8_t  _phase;
    float    _angleRad;
    uint32_t _lastTickMs;
    bool     _leadIn;      // Smooth approach to start position

    void _enqueueNextPhase();
};

#endif
