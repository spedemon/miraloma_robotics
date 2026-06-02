/**
 * StatusLed.cpp — Mira Status LED Implementation
 *
 * Breathing animation using a raised-cosine curve for perceptually smooth
 * fading. Runs as an independent FreeRTOS task at low priority.
 */

#include "StatusLed.h"
#include <math.h>

// Animation update interval — ~60 fps is more than enough for smooth fading
static const TickType_t kUpdateIntervalMs = 16;

StatusLed::StatusLed()
    : _taskHandle(nullptr) {
}

void StatusLed::begin() {
    // Attach LEDC to the LED pin (Arduino ESP32 core 3.x API)
    ledcAttach(LED_PIN, LED_PWM_FREQ, LED_PWM_RESOLUTION);

    // Start with LED off
    ledcWrite(LED_PIN, LED_ACTIVE_LOW ? ((1 << LED_PWM_RESOLUTION) - 1) : 0);

    // Launch breathing task
    xTaskCreate(
        _breatheTask,       // Task function
        "led_breathe",      // Name (for debugging)
        LED_TASK_STACK,      // Stack size
        this,                // Parameter (this instance)
        LED_TASK_PRIORITY,   // Priority
        &_taskHandle         // Handle
    );

    Serial.println("[StatusLed] Breathing started");
}

void StatusLed::_breatheTask(void* pvParameters) {
    const uint16_t maxDuty = (1 << LED_PWM_RESOLUTION) - 1; // 255 for 8-bit

    for (;;) {
        // Current position in the breath cycle (0.0 – 1.0)
        float phase = (float)(millis() % LED_BREATH_PERIOD_MS) / (float)LED_BREATH_PERIOD_MS;

        // Raised cosine: 0→1→0 over one cycle, perceptually smooth
        // (1 - cos(2π·phase)) / 2
        float brightness = (1.0f - cosf(2.0f * M_PI * phase)) / 2.0f;

        // Convert to duty cycle
        uint16_t duty = (uint16_t)(brightness * maxDuty);

        // Invert for active-low LED
        if (LED_ACTIVE_LOW) {
            duty = maxDuty - duty;
        }

        ledcWrite(LED_PIN, duty);

        vTaskDelay(pdMS_TO_TICKS(kUpdateIntervalMs));
    }
}
