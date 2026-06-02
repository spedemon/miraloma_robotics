/**
 * BoostButton.h — BOOT button mode-cycle controller
 *
 * Debounces the BOOT button (GPIO 9, active LOW) on the ESP32-C3
 * Super Mini and cycles through gesture demo modes on each press:
 *
 *   idle → wave → idle → bow → idle → fcircle → idle → crab
 *   → idle → dance → idle → (wrap to wave)
 *
 * The button uses an interrupt for edge detection with a
 * millis()-based debounce window. The main loop polls wasPressed()
 * to advance through the mode table.
 */

#ifndef MIRA_BOOST_BUTTON_H
#define MIRA_BOOST_BUTTON_H

#include <Arduino.h>
#include "config.h"
#include "Gesture.h"
#include "ArmController.h"

class BoostButton {
public:
    BoostButton(GestureManager& gestures, ArmController& controller);

    /** Call once in setup() after gestures are registered. */
    void begin();

    /** Call every loop() iteration. Advances mode on button press. */
    void update();

private:
    GestureManager& _gestures;
    ArmController&  _controller;

    // ISR state (volatile for ISR ↔ loop communication)
    static volatile bool     _isrFlag;
    static volatile uint32_t _lastIsrMs;

    static void IRAM_ATTR _isrHandler();

    bool _wasPressed();          // Consume the ISR flag (non-blocking)
    void _goIdle();              // Stop gesture, home arm
    void _startMode();           // Start the current gesture

    // Mode table: alternating nullptr (idle) and gesture name strings.
    // nullptr entries represent idle pauses; non-null are gesture names.
    static const char* const MODE_TABLE[];
    static const uint8_t     MODE_COUNT;

    uint8_t _modeIndex;          // Current position in MODE_TABLE
};

#endif // MIRA_BOOST_BUTTON_H
