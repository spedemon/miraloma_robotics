/**
 * Gesture.cpp — GestureManager Implementation
 */

#include "Gesture.h"
#include <string.h>

GestureManager::GestureManager()
    : _count(0), _active(nullptr) {
}

void GestureManager::registerGesture(Gesture* g) {
    if (_count < MAX_GESTURES) {
        _gestures[_count++] = g;
    }
}

void GestureManager::update() {
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

    // Stop any running gesture first (interruptible)
    stopAll();

    _active = g;
    g->start();
    return true;
}

void GestureManager::stopAll() {
    if (_active) {
        _active->stop();
        _active = nullptr;
    }
}

Gesture* GestureManager::active() {
    return _active;
}

uint8_t GestureManager::count() const {
    return _count;
}

Gesture* GestureManager::get(uint8_t index) const {
    if (index < _count) return _gestures[index];
    return nullptr;
}
