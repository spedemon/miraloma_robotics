/**
 * FCircleGesture.h — Smooth front-facing parametric circle
 */
#ifndef MIRA_FCIRCLE_GESTURE_H
#define MIRA_FCIRCLE_GESTURE_H

#include "Gesture.h"

class FCircleGesture : public Gesture {
public:
    FCircleGesture(MotionPlanner& planner, ArmController& ctrl);
    const char* name() override { return "fcircle"; }
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
    float    _angleRad;
    uint32_t _lastTickMs;
};

#endif
