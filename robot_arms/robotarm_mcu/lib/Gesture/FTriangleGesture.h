/**
 * FTriangleGesture.h — Smooth front-facing triangle via edge-walking
 */
#ifndef MIRA_FTRIANGLE_GESTURE_H
#define MIRA_FTRIANGLE_GESTURE_H

#include "Gesture.h"

class FTriangleGesture : public Gesture {
public:
    FTriangleGesture(MotionPlanner& planner, ArmController& ctrl);
    const char* name() override { return "ftriangle"; }
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
    uint8_t  _edge;
    float    _t;
    uint32_t _lastTickMs;
    uint32_t _holdStartMs;
    bool     _holding;
    bool     _leadIn;      // Smooth approach to start position
};

#endif
