/**
 * Gesture.cpp — GestureManager Implementation
 *
 * When a new gesture is requested while another is running,
 * the manager:
 *   1. Stops the current gesture (sets _running = false)
 *   2. Starts a smooth timed move to home position
 *   3. Waits for the homing move to complete
 *   4. Starts the pending gesture
 *
 * This eliminates the jerky snap that occurred when jumping
 * directly from one gesture's pose to another.
 */

#include "Gesture.h"
#include "config.h"
#include <string.h>

GestureManager::GestureManager(SmoothMover& smooth, MotionPlanner& planner)
    : _count(0), _active(nullptr),
      _pending(nullptr), _transitioning(false),
      _smooth(smooth), _planner(planner) {
}

void GestureManager::registerGesture(Gesture* g) {
    if (_count < MAX_GESTURES) {
        _gestures[_count++] = g;
    }
}

void GestureManager::unregisterGesture(Gesture* g) {
    for (uint8_t i = 0; i < _count; i++) {
        if (_gestures[i] == g) {
            // Shift remaining gestures down
            for (uint8_t j = i; j < _count - 1; j++) {
                _gestures[j] = _gestures[j + 1];
            }
            _count--;
            // Clear active/pending if they reference this gesture
            if (_active == g) {
                _active->stop();
                _active = nullptr;
            }
            if (_pending == g) {
                _pending = nullptr;
            }
            return;
        }
    }
}

void GestureManager::update() {
    // --- Transition logic: wait for homing to finish, then start pending ---
    if (_transitioning) {
        if (!_smooth.isBusy() && !_planner.isBusy()) {
            // Homing complete — start the pending gesture
            _transitioning = false;
            if (_pending) {
                _active = _pending;
                _pending = nullptr;
                _active->start();
                Serial.println("[GestureManager] Transition complete → starting gesture");
            }
        }
        return;  // Don't update any gesture while transitioning
    }

    // --- Normal gesture update ---
    if (_active && _active->isRunning()) {
        _active->update();
    } else if (_active && !_active->isRunning()) {
        // Gesture finished on its own (one-shot)
        _active = nullptr;
    }
}

Gesture* GestureManager::find(const char* name) {
    for (uint8_t i = 0; i < _count; i++) {
        if (strcmp(_gestures[i]->name(), name) == 0) {
            return _gestures[i];
        }
    }
    return nullptr;
}

bool GestureManager::startGesture(const char* name) {
    Gesture* g = find(name);
    if (!g) return false;

    // If we're already transitioning, just replace the pending gesture
    if (_transitioning) {
        _pending = g;
        Serial.println("[GestureManager] Updated pending gesture during transition");
        return true;
    }

    // If a gesture is currently active, transition through home first
    if (_active && _active->isRunning()) {
        // Stop the current gesture (just flag it, don't trigger its own homing)
        _active->stop();
        _active = nullptr;

        // Clear any residual planner/smooth motion from the stopped gesture
        _planner.clearQueue();
        _smooth.stopAll();

        // Start smooth homing move
        _smooth.startTimedMove(HOME_BASE, HOME_SHOULDER, HOME_ELBOW, HOME_GRIP,
                               TRANSITION_HOME_MS);

        // Queue the new gesture as pending
        _pending = g;
        _transitioning = true;
        Serial.println("[GestureManager] Transitioning to home before next gesture");
        return true;
    }

    // No gesture running — start immediately
    // (Still do a quick home if we're not already there)
    stopAll();

    _active = g;
    g->start();
    return true;
}

void GestureManager::stopAll() {
    _pending = nullptr;
    _transitioning = false;

    if (_active) {
        _active->stop();
        _active = nullptr;
    }
}

Gesture* GestureManager::active() {
    return _active;
}

bool GestureManager::isTransitioning() const {
    return _transitioning;
}

uint8_t GestureManager::count() const {
    return _count;
}

Gesture* GestureManager::get(uint8_t index) const {
    if (index < _count) return _gestures[index];
    return nullptr;
}
