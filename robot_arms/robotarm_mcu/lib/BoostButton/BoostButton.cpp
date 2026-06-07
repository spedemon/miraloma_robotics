/**
 * BoostButton.cpp — BOOT button mode-cycle implementation
 */

#include "BoostButton.h"

// ---------------------------------------------------------------------------
// Mode table
// ---------------------------------------------------------------------------
// nullptr = idle (stop gesture, go home)
// string  = gesture name to start
//
// Sequence: idle → wave → idle → bow → idle → fcircle → idle → crab
//           → idle → dance → (wrap)

const char* const BoostButton::MODE_TABLE[] = {
    nullptr,     // 0 - idle (initial)
    "custom",    // NEW!
    nullptr,
    "wave",      // 1
    nullptr,     // 2 - idle
    "bow",       // 3
    nullptr,     // 4 - idle
    "fcircle",   // 5 - front circle
    nullptr,     // 6 - idle
    "crab",      // 7
    nullptr,     // 8 - idle
    "dance",     // 9
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

BoostButton::BoostButton(GestureManager& gestures, ArmController& controller)
    : _gestures(gestures)
    , _controller(controller)
    , _modeIndex(0)
{
}

void BoostButton::begin() {
    pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(BOOT_BUTTON_PIN),
                    _isrHandler, FALLING);

    Serial.println("[BoostButton] BOOT button ready on GPIO "
                   + String(BOOT_BUTTON_PIN));
    Serial.println("[BoostButton] Press to cycle: idle → wave → idle → "
                   "bow → idle → fcircle → idle → crab → idle → dance");
}

void BoostButton::update() {
    if (!_wasPressed()) return;

    // Advance to next mode (wrap around)
    _modeIndex = (_modeIndex + 1) % MODE_COUNT;

    const char* mode = MODE_TABLE[_modeIndex];

    if (mode == nullptr) {
        _goIdle();
    } else {
        _startMode();
    }
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
    // The main loop auto-home logic will detect the gesture→inactive
    // transition and smoothly return to home, then sleep.
    Serial.println("[BoostButton] → idle (auto-homing)");
}

void BoostButton::_startMode() {
    const char* name = MODE_TABLE[_modeIndex];
    Serial.print("[BoostButton] → ");
    Serial.println(name);

    if (!_gestures.startGesture(name)) {
        Serial.print("[BoostButton] ERROR: gesture '");
        Serial.print(name);
        Serial.println("' not found!");
    }
}
