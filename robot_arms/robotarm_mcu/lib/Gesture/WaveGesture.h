/**
 * WaveGesture.h — Sinusoidal wave with slow base sweep
 *
 * Shoulder and elbow oscillate with a phase offset to create a
 * propagating wave. The base rotates slowly (1/10 wave speed)
 * to "show off" the wave to a surrounding audience.
 */

#ifndef MIRA_WAVE_GESTURE_H
#define MIRA_WAVE_GESTURE_H

#include "Gesture.h"
#include "SmoothMover.h"

class WaveGesture : public Gesture {
public:
    WaveGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth);

    const char* name() override { return "wave"; }
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
    uint32_t _startMs;
    uint32_t _lastTickMs;
};

#endif // MIRA_WAVE_GESTURE_H
