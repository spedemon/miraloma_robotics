/**
 * main.cpp — Mira Motor MCU
 *
 * Initializes all layers and runs the non-blocking main loop:
 *   - MotionPlanner: interpolates waypoints → ArmController
 *   - GestureManager: feeds waypoints into MotionPlanner
 *   - SerialConsole: processes user commands (USB + swarm)
 *   - SwarmNode: ESP-NOW radio (auto-discovery + command relay)
 *   - StatusLed: breathes independently (FreeRTOS task)
 */

#include <Arduino.h>
#include "config.h"
#include "MiraArm.h"
#include "ArmController.h"
#include "MotionPlanner.h"
#include "Gesture.h"
#include "DanceGesture.h"
#include "BowGesture.h"
#include "CrabGesture.h"
#include "BreakGesture.h"
#include "CircleGesture.h"
#include "SquareGesture.h"
#include "TriangleGesture.h"
#include "FCircleGesture.h"
#include "FSquareGesture.h"
#include "FTriangleGesture.h"
#include "StatusLed.h"
#include "SmoothMover.h"
#include "SerialConsole.h"
#include "SwarmNode.h"

// --- Layer 0: PWM driver ---
MiraArm arm;

// --- Layer 1: IK + Cartesian control ---
ArmController controller(arm);

// --- Layer 2: Non-blocking motion ---
MotionPlanner planner(controller);

// --- Smooth joint-space motion ---
SmoothMover smooth(controller);

// --- Layer 3: Gestures ---
GestureManager gestures;
DanceGesture   danceGesture(planner, controller);
BowGesture     bowGesture(planner, controller, smooth);
CrabGesture    crabGesture(planner, controller);
BreakGesture   breakGesture(planner, controller);
CircleGesture  circleGesture(planner, controller);
SquareGesture  squareGesture(planner, controller);
TriangleGesture triangleGesture(planner, controller);
FCircleGesture  fcircleGesture(planner, controller);
FSquareGesture  fsquareGesture(planner, controller);
FTriangleGesture ftriangleGesture(planner, controller);

// --- Peripherals ---
StatusLed led;

// --- Console ---
SerialConsole console(arm, controller, planner, gestures, smooth);

// --- Swarm (ESP-NOW) ---
SwarmNode swarmNode;

// ---------------------------------------------------------------------------
// Swarm command handler — bridges ESP-NOW commands to SerialConsole
// ---------------------------------------------------------------------------

void handleSwarmCommand(const char* command, char* response, size_t maxLen) {
    String cmd(command);
    String resp;

    // Execute the command through the console engine
    console.executeCommand(cmd, resp);

    // Copy response to the output buffer
    if (resp.length() > 0) {
        size_t copyLen = resp.length();
        if (copyLen >= maxLen) copyLen = maxLen - 1;
        memcpy(response, resp.c_str(), copyLen);
        response[copyLen] = '\0';
    }
}

// ---------------------------------------------------------------------------
// Arduino entry points
// ---------------------------------------------------------------------------

void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(1000);  // Give USB CDC time to enumerate

    Serial.println();
    Serial.println("========================================");
    Serial.println("  Mira Motor MCU — v0.4.0 (Swarm)");
    Serial.println("  3-DOF Robot Arm Controller");
    Serial.println("========================================");
    Serial.println();

    led.begin();

    arm.begin();
    controller.begin();
    controller.home();
    delay(500);

    // Register gestures
    gestures.registerGesture(&danceGesture);
    gestures.registerGesture(&bowGesture);
    gestures.registerGesture(&crabGesture);
    gestures.registerGesture(&breakGesture);
    gestures.registerGesture(&circleGesture);
    gestures.registerGesture(&squareGesture);
    gestures.registerGesture(&triangleGesture);
    gestures.registerGesture(&fcircleGesture);
    gestures.registerGesture(&fsquareGesture);
    gestures.registerGesture(&ftriangleGesture);

    console.begin();

    // --- Swarm init ---
    swarmNode.onCommand(handleSwarmCommand);
    swarmNode.begin();
}

void loop() {
    planner.update();     // Interpolate → ArmController
    smooth.update();      // Smooth joint-space motions
    gestures.update();    // Feed planner if a gesture is active
    console.update();     // Process serial input (USB)
    swarmNode.update();   // Process swarm commands (ESP-NOW)
}
