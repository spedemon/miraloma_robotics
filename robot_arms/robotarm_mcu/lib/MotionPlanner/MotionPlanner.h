/**
 * MotionPlanner.h — Mira Motion Planner (Layer 2)
 *
 * Non-blocking waypoint queue with linear interpolation.
 * Enqueue target positions; the planner smoothly moves the arm
 * by calling ArmController at ~50 Hz.
 */

#ifndef MIRA_MOTION_PLANNER_H
#define MIRA_MOTION_PLANNER_H

#include <Arduino.h>
#include "config.h"
#include "ArmController.h"

struct Waypoint {
    float x, y, z;    // End-effector position (mm)
    float grip;        // Grip angle (degrees)
    float speed;       // End-effector speed (mm/s), 0 = instant
};

class MotionPlanner {
public:
    MotionPlanner(ArmController& ctrl);

    /**
     * Update interpolation. Call every loop() iteration.
     * Self-throttles to MOTION_UPDATE_INTERVAL_MS.
     */
    void update();

    /**
     * Enqueue a waypoint for smooth motion.
     * @return true if enqueued, false if queue is full.
     */
    bool enqueue(float x, float y, float z, float grip, float speed = MOTION_DEFAULT_SPEED);

    /**
     * Clear all pending waypoints and stop motion immediately.
     */
    void clearQueue();

    /**
     * Move to a position immediately (clears queue first).
     */
    void moveNow(float x, float y, float z, float grip);

    /** Is the planner currently moving (queue not empty or interpolating)? */
    bool isBusy() const;

    /** Is the planner idle (nothing to do)? */
    bool isIdle() const;

    /** Number of waypoints currently in the queue. */
    uint8_t queueSize() const;

    static const uint8_t MAX_QUEUE = MOTION_QUEUE_SIZE;

private:
    ArmController& _ctrl;

    // Circular buffer for waypoints
    Waypoint _queue[MOTION_QUEUE_SIZE];
    uint8_t  _head;       // Next write position
    uint8_t  _tail;       // Next read position
    uint8_t  _count;      // Number of items in queue

    // Interpolation state
    bool     _interpolating;
    float    _startX, _startY, _startZ, _startGrip;
    float    _targetX, _targetY, _targetZ, _targetGrip;
    uint32_t _moveStartMs;
    uint32_t _moveDurationMs;
    uint32_t _lastUpdateMs;

    // Internal helpers
    bool _dequeue(Waypoint& wp);
    void _startInterpolation(const Waypoint& wp);
};

#endif // MIRA_MOTION_PLANNER_H
