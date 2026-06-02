/**
 * StatusLed.h — Mira Status LED (Breathing Animation)
 *
 * Runs a smooth breathing animation on the onboard LED using the ESP32
 * LEDC peripheral for hardware PWM. The animation runs in its own
 * FreeRTOS task, so it stays smooth regardless of what the main loop
 * is doing (including blocking delays).
 */

#ifndef MIRA_STATUS_LED_H
#define MIRA_STATUS_LED_H

#include <Arduino.h>
#include "config.h"

class StatusLed {
public:
    StatusLed();

    /**
     * Initialize LEDC PWM and start the breathing task.
     * Call once in setup().
     */
    void begin();

private:
    /**
     * FreeRTOS task function (static so it can be used as a task entry point).
     * Receives the StatusLed instance pointer via pvParameters.
     */
    static void _breatheTask(void* pvParameters);

    TaskHandle_t _taskHandle;
};

#endif // MIRA_STATUS_LED_H
