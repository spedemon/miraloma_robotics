/**
 * DanceGesture.h — Data-driven dance gesture (50 joint-angle keyframes)
 *
 * Plays a looping sequence of joint-space keyframes using SmoothMover's
 * timed moves. Each keyframe specifies base/shoulder/elbow/grip angles
 * and a duration. Speed parameter acts as a global time-scale multiplier.
 */

#ifndef MIRA_DANCE_GESTURE_H
#define MIRA_DANCE_GESTURE_H

#include "Gesture.h"
#include "SmoothMover.h"

class DanceGesture : public Gesture {
public:
    DanceGesture(ArmController& ctrl, SmoothMover& smooth);

    const char* name() override { return "dance"; }
    void start() override;
    void stop() override;
    void update() override;
    bool isRunning() override;
    bool hasSpeed() override { return true; }
    void setSpeed(float speed) override;

private:
    ArmController&  _ctrl;
    SmoothMover&    _smooth;
    bool            _running;
    float           _timeScale;   // 1.0 = normal, <1 = slower, >1 = faster
    uint8_t         _phase;

    void _enqueueNextKeyframe();
};

#endif // MIRA_DANCE_GESTURE_H
