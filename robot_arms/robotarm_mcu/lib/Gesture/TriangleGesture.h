/**
 * TriangleGesture.h — Smooth triangle via edge-walking
 */
#ifndef MIRA_TRIANGLE_GESTURE_H
#define MIRA_TRIANGLE_GESTURE_H

#include "Gesture.h"
#include "SmoothMover.h"

class TriangleGesture : public Gesture {
public:
    TriangleGesture(MotionPlanner& planner, ArmController& ctrl, SmoothMover& smooth);
    const char* name() override { return "triangle"; }
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
    uint8_t  _edge;
    float    _t;
    uint32_t _lastTickMs;
    uint32_t _holdStartMs;
    bool     _holding;
    bool     _leadIn;      // Smooth approach to start position
};

#endif
