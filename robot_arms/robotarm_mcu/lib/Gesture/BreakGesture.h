/**
 * BreakGesture.h — Break dance gesture
 */

#ifndef MIRA_BREAK_GESTURE_H
#define MIRA_BREAK_GESTURE_H

#include "Gesture.h"

class BreakGesture : public Gesture {
public:
    BreakGesture(MotionPlanner& planner, ArmController& ctrl);

    const char* name() override { return "break"; }
    void start() override;
    void stop() override;
    void update() override;
    bool isRunning() override;
    bool hasSpeed() override { return true; }
    void setSpeed(float speed) override;

private:
    MotionPlanner&  _planner;
    ArmController&  _ctrl;
    bool            _running;
    float           _speed;
    uint8_t         _phase;

    void _enqueueNextPhase();
};

#endif // MIRA_BREAK_GESTURE_H
