/**
 * CrabGesture.h — Looping crab-bites sequence
 */

#ifndef MIRA_CRAB_GESTURE_H
#define MIRA_CRAB_GESTURE_H

#include "Gesture.h"
#include "SmoothMover.h"

class CrabGesture : public Gesture {
public:
    CrabGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth);

    const char* name() override { return "crab"; }
    void start() override;
    void stop() override;
    void update() override;
    bool isRunning() override;
    bool hasSpeed() override { return true; }
    void setSpeed(float speed) override;

private:
    MotionPlanner&  _planner;
    ArmController&  _ctrl;
    SmoothMover&    _smooth;
    bool            _running;
    float           _speed;
    uint8_t         _phase;

    void _enqueueNextPhase();
};

#endif // MIRA_CRAB_GESTURE_H
