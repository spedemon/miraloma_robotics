/**
 * CircleGesture.h — Smooth parametric circle
 */
#ifndef MIRA_CIRCLE_GESTURE_H
#define MIRA_CIRCLE_GESTURE_H

#include "Gesture.h"

class CircleGesture : public Gesture {
public:
    CircleGesture(MotionPlanner& planner, ArmController& ctrl);
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
    bool     _running;
    float    _speed;
    uint8_t  _phase;
    float    _angleRad;
    uint32_t _lastTickMs;

    void _enqueueNextPhase();
};

#endif
