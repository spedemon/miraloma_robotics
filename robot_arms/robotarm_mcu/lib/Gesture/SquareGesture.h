/**
 * SquareGesture.h — Smooth square via edge-walking
 */
#ifndef MIRA_SQUARE_GESTURE_H
#define MIRA_SQUARE_GESTURE_H

#include "Gesture.h"

class SquareGesture : public Gesture {
public:
    SquareGesture(MotionPlanner& planner, ArmController& ctrl);
    const char* name() override { return "square"; }
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
    uint8_t  _edge;       // Current edge (0-3)
    float    _t;           // Progress along edge (0.0 - 1.0)
    uint32_t _lastTickMs;
    uint32_t _holdStartMs;
    bool     _holding;     // In corner-hold mode
};

#endif
