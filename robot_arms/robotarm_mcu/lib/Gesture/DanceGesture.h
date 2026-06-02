/**
 * DanceGesture.h — Looping side-to-side sway with bobbing
 */

#ifndef MIRA_DANCE_GESTURE_H
#define MIRA_DANCE_GESTURE_H

#include "Gesture.h"

class DanceGesture : public Gesture {
public:
    DanceGesture(MotionPlanner& planner, ArmController& ctrl);

    const char* name() override { return "dance"; }
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

#endif // MIRA_DANCE_GESTURE_H
