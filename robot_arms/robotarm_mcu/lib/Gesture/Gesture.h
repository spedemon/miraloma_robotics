/**
 * Gesture.h — Mira Gesture System (Layer 3)
 *
 * Base class for all gestures and a GestureManager that registers
 * and dispatches them. Gestures feed waypoints into the MotionPlanner.
 *
 * When switching between gestures, the manager smoothly transitions
 * through the home position to avoid jerky movements.
 */

#ifndef MIRA_GESTURE_H
#define MIRA_GESTURE_H

#include <Arduino.h>
#include "MotionPlanner.h"
#include "SmoothMover.h"

// ---------------------------------------------------------------------------
// Gesture base class
// ---------------------------------------------------------------------------

class Gesture {
public:
    virtual ~Gesture() {}

    /** Human-readable name (used by console). */
    virtual const char* name() = 0;

    /** Start the gesture. */
    virtual void start() = 0;

    /** Request stop (gesture finishes cleanly). */
    virtual void stop() = 0;

    /**
     * Called every loop() iteration while running.
     * Feed new waypoints to the planner as needed.
     */
    virtual void update() = 0;

    /** Is this gesture currently running? */
    virtual bool isRunning() = 0;

    /** Is this gesture empty / has no content loaded? */
    virtual bool isEmpty() { return false; }

    /** Does this gesture support a speed parameter? */
    virtual bool hasSpeed() { return false; }

    /** Set speed (mm/s). Override in gestures that support it. */
    virtual void setSpeed(float speed) { (void)speed; }
};

// ---------------------------------------------------------------------------
// GestureManager — registry and dispatcher
// ---------------------------------------------------------------------------

class GestureManager {
public:
    static const uint8_t MAX_GESTURES = 32;

    /** Duration of the smooth home transition between gestures (ms). */
    static const uint32_t TRANSITION_HOME_MS = 800;

    GestureManager(SmoothMover& smooth, MotionPlanner& planner);

    /** Register a gesture. Call during setup(). */
    void registerGesture(Gesture* g);

    /** Remove a gesture from the registry. Used when deleting custom gestures. */
    void unregisterGesture(Gesture* g);

    /**
     * Update active gesture and transition logic.
     * Call every loop() iteration.
     */
    void update();

    /** Find a gesture by name (case-sensitive). Returns nullptr if not found. */
    Gesture* find(const char* name);

    /** Start a gesture by name. If another is running, transitions via home first. */
    bool startGesture(const char* name);

    /** Stop whatever gesture is currently running. */
    void stopAll();

    /** Get the currently active gesture (or nullptr). */
    Gesture* active();

    /** Is the manager currently transitioning between gestures? */
    bool isTransitioning() const;

    // Iteration for listing
    uint8_t count() const;
    Gesture* get(uint8_t index) const;

private:
    Gesture* _gestures[MAX_GESTURES];
    uint8_t  _count;
    Gesture* _active;

    // Transition state
    Gesture*       _pending;       // Gesture to start after homing
    bool           _transitioning; // true while smooth-homing before next gesture
    SmoothMover&   _smooth;
    MotionPlanner& _planner;
};

#endif // MIRA_GESTURE_H
