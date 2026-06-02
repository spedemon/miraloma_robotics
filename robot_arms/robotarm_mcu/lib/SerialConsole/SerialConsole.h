/**
 * SerialConsole.h — Mira Serial Command Console
 *
 * Interactive terminal over USB serial for controlling the robot arm.
 * Also provides executeCommand() for programmatic use (e.g., swarm).
 *
 * Commands:
 *   help                       — Show available commands
 *   home                       — Move all servos to home position
 *   where                      — Print current position (FK)
 *   joints                     — Print current joint angles
 *
 *   set <joint> <angle>        — Set a servo angle directly (0–180)
 *   goto <x> <y> <z>           — Move to Cartesian position (instant, via IK)
 *   grip <angle>               — Set grip angle
 *
 *   move <x> <y> <z> [speed]   — Smooth move (default 50 mm/s)
 *   stop                       — Clear motion queue and stop gestures
 *
 *   gesture list               — List available gestures
 *   gesture <name>             — Start a gesture
 *   gesture <name> stop        — Stop a running gesture
 *   gesture <name> speed <v>   — Set gesture speed
 *
 *   smset <joint> <angle>       — Smooth joint move (trapezoidal profile)
 *   timed_set B S E G <ms>      — Timed move (all joints simultaneously)
 *   smparam                     — Show smooth motion parameters
 *   smparam speed <v>           — Set max speed (deg/s)
 *   smparam accel <a>           — Set acceleration (deg/s²)
 *
 *   rawset <joint> <µs>         — Set raw PWM pulse width (µs)
 *
 *   test base|shoulder|elbow|grip|wave|all — Blocking servo tests
 */

#ifndef MIRA_SERIAL_CONSOLE_H
#define MIRA_SERIAL_CONSOLE_H

#include <Arduino.h>
#include "config.h"
#include "MiraArm.h"
#include "ArmController.h"
#include "MotionPlanner.h"
#include "Gesture.h"
#include "SmoothMover.h"

class SerialConsole {
public:
    SerialConsole(MiraArm& arm, ArmController& ctrl,
                  MotionPlanner& planner, GestureManager& gestures,
                  SmoothMover& smooth);

    void begin();
    void update();

    /**
     * Execute a command string programmatically.
     * Output goes to Serial (same as interactive use).
     */
    void executeCommand(const String& cmd);

    /**
     * Execute a command and capture output to a String buffer.
     * Used by SwarmNode to send responses over ESP-NOW.
     * @param cmd       Command string (e.g., "home", "goto 50 0 60")
     * @param response  Output buffer — receives all text that would
     *                  normally go to Serial.
     */
    void executeCommand(const String& cmd, String& response);

private:
    MiraArm&        _arm;
    ArmController&  _ctrl;
    MotionPlanner&  _planner;
    GestureManager& _gestures;
    SmoothMover&    _smooth;
    String          _inputBuffer;

    // --- Output redirection ---
    String*         _captureBuffer;  // Non-null when capturing output

    /** Print helper — writes to Serial or capture buffer. */
    void _out(const char* str);
    void _out(const String& str);
    void _outln(const char* str);
    void _outln(const String& str);
    void _outln();  // Just newline

    // --- Command dispatch ---
    void _processCommand(const String& line);
    void _cmdHelp();
    void _cmdHome();
    void _cmdWhere();
    void _cmdJoints();
    void _cmdSet(const String& args);
    void _cmdGoto(const String& args);
    void _cmdGrip(const String& args);
    void _cmdMove(const String& args);
    void _cmdStop();
    void _cmdGesture(const String& args);
    void _cmdSmset(const String& args);
    void _cmdTimedSet(const String& args);
    void _cmdSmparam(const String& args);
    void _cmdRawset(const String& args);
    void _cmdTest(const String& args);

    // --- Test routines (blocking, for servo-level debugging) ---
    void _testBase();
    void _testShoulder();
    void _testElbow();
    void _testGrip();
    void _testCombinedWave();
    void _testAll();

    // --- Helpers ---
    void _printPrompt();
    int  _resolveJoint(const String& name);
    bool _parseFloat(const String& str, float& value);

    /**
     * Stop any gesture and clear planner before a direct command.
     * Called by goto, grip, move, home to make them interruptible.
     */
    void _interruptMotion();
};

#endif // MIRA_SERIAL_CONSOLE_H
