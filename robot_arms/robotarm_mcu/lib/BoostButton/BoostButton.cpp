/**
 * BoostButton.cpp — BOOT button mode-cycle implementation
 *
 * Cycles through built-in gestures from the static MODE_TABLE, then
 * appends any custom gestures from CustomGestureStore. Empty/unloaded
 * gestures are automatically skipped.
 */

#include "BoostButton.h"
#include "CustomGestureStore.h"

// ---------------------------------------------------------------------------
// Mode table (built-in gestures)
// ---------------------------------------------------------------------------
// nullptr = idle (stop gesture, go home)
// string  = gesture name to start
//
// Sequence: idle → wave → idle → bow → idle → fcircle → idle → crab
//           → idle → dance → idle → break → idle → [custom gestures...] → (wrap)

const char* const BoostButton::MODE_TABLE[] = {
    nullptr,     // 0 - idle (initial)
    "wave",      // 1
    nullptr,     // 2 - idle
    "bow",       // 3
    nullptr,     // 4 - idle
    "fcircle",   // 5 - front circle
    nullptr,     // 6 - idle
    "crab",      // 7
    nullptr,     // 8 - idle
    "dance",     // 9
    nullptr,     // 10 - idle
    "break",     // 11 - break dance
    nullptr,     // 12 - idle (before custom range)
};

const uint8_t BoostButton::MODE_COUNT =
    sizeof(MODE_TABLE) / sizeof(MODE_TABLE[0]);

// ---------------------------------------------------------------------------
// ISR state (shared between ISR and loop context)
// ---------------------------------------------------------------------------

volatile bool     BoostButton::_isrFlag   = false;
volatile uint32_t BoostButton::_lastIsrMs = 0;

// ---------------------------------------------------------------------------
// ISR handler — minimal work: debounce + set flag
// ---------------------------------------------------------------------------

void IRAM_ATTR BoostButton::_isrHandler() {
    uint32_t now = millis();
    if (now - _lastIsrMs >= BOOT_BUTTON_DEBOUNCE_MS) {
        _isrFlag   = true;
        _lastIsrMs = now;
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

BoostButton::BoostButton(GestureManager& gestures, ArmController& controller,
                         CustomGestureStore* customStore)
    : _gestures(gestures)
    , _controller(controller)
    , _customStore(customStore)
    , _modeIndex(0)
    , _inCustomRange(false)
    , _customSlotIndex(0)
{
}

void BoostButton::begin() {
    pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(BOOT_BUTTON_PIN),
                    _isrHandler, FALLING);

    Serial.println("[BoostButton] BOOT button ready on GPIO "
                   + String(BOOT_BUTTON_PIN));
    Serial.println("[BoostButton] Press to cycle through gestures + custom");
}

void BoostButton::update() {
    if (!_wasPressed()) return;

    // Try advancing up to a reasonable number of times to find a valid mode
    uint8_t maxAttempts = MODE_COUNT + (_customStore ? CustomGestureStore::MAX_CUSTOM_GESTURES * 2 : 0);

    for (uint8_t attempts = 0; attempts < maxAttempts; attempts++) {
        _advanceMode();
        const char* mode = _currentModeName();

        if (mode == nullptr) {
            // idle entry — always valid
            _goIdle();
            return;
        }

        // Check if the gesture has content loaded
        Gesture* g = _gestures.find(mode);
        if (g && g->isEmpty()) {
            Serial.print("[BoostButton] skipping empty gesture: ");
            Serial.println(mode);
            // Skip the gesture AND the idle entry after it
            _advanceMode();
            continue;
        }

        if (!g) {
            // Gesture not found (maybe deleted) — skip it + idle after
            Serial.print("[BoostButton] skipping missing gesture: ");
            Serial.println(mode);
            _advanceMode();
            continue;
        }

        _startMode();
        return;
    }

    // All modes empty — fall back to idle
    _goIdle();
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

bool BoostButton::_wasPressed() {
    if (_isrFlag) {
        _isrFlag = false;
        return true;
    }
    return false;
}

void BoostButton::_goIdle() {
    _gestures.stopAll();
    Serial.println("[BoostButton] → idle (auto-homing)");
}

void BoostButton::_startMode() {
    const char* name = _currentModeName();
    Serial.print("[BoostButton] → ");
    Serial.println(name);

    if (!_gestures.startGesture(name)) {
        Serial.print("[BoostButton] ERROR: gesture '");
        Serial.print(name);
        Serial.println("' not found!");
    }
}

const char* BoostButton::_currentModeName() {
    if (!_inCustomRange) {
        return MODE_TABLE[_modeIndex];
    }

    // In custom range: alternate between custom gesture and idle
    // Even _customSlotIndex values are gestures, odd are idles
    // But we handle this differently: we use _customSlotIndex to
    // find the next used slot in the store
    if (_customStore) {
        return _customStore->getName(_customSlotIndex);
    }
    return nullptr;
}

void BoostButton::_advanceMode() {
    if (!_inCustomRange) {
        _modeIndex = (_modeIndex + 1) % MODE_COUNT;

        // If we've wrapped back to the beginning, check if we should
        // enter the custom range first
        if (_modeIndex == 0 && _customStore && _customStore->count() > 0) {
            _inCustomRange = true;
            _customSlotIndex = 0;
            // Find first used slot
            while (_customSlotIndex < CustomGestureStore::MAX_CUSTOM_GESTURES &&
                   !_customStore->getName(_customSlotIndex)) {
                _customSlotIndex++;
            }
            if (_customSlotIndex >= CustomGestureStore::MAX_CUSTOM_GESTURES) {
                // No custom gestures found, stay in built-in range
                _inCustomRange = false;
            }
            return;
        }
    } else {
        // Advance within custom range: find the next used slot
        _customSlotIndex++;
        while (_customSlotIndex < CustomGestureStore::MAX_CUSTOM_GESTURES &&
               !_customStore->getName(_customSlotIndex)) {
            _customSlotIndex++;
        }

        if (_customSlotIndex >= CustomGestureStore::MAX_CUSTOM_GESTURES) {
            // Exhausted custom gestures — wrap back to built-in
            _inCustomRange = false;
            _modeIndex = 0;  // Start from idle
        }
    }
}
