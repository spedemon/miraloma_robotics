/**
 * SerialConsole.cpp — Mira Serial Command Console Implementation
 *
 * All command output uses _out()/_outln() helpers so that output
 * can be redirected to a capture buffer (for swarm responses).
 */

#include "SerialConsole.h"

SerialConsole::SerialConsole(MiraArm& arm, ArmController& ctrl,
                             MotionPlanner& planner, GestureManager& gestures,
                             SmoothMover& smooth)
    : _arm(arm), _ctrl(ctrl), _planner(planner), _gestures(gestures),
      _smooth(smooth), _captureBuffer(nullptr) {
}

void SerialConsole::begin() {
    Serial.println("Type 'help' for available commands.");
    Serial.println();
    _printPrompt();
}

// ---------------------------------------------------------------------------
// Public command execution API
// ---------------------------------------------------------------------------

void SerialConsole::executeCommand(const String& cmd) {
    _captureBuffer = nullptr;
    _processCommand(cmd);
}

void SerialConsole::executeCommand(const String& cmd, String& response) {
    response = "";
    _captureBuffer = &response;
    _processCommand(cmd);
    _captureBuffer = nullptr;
}

// ---------------------------------------------------------------------------
// Output helpers — write to Serial or capture buffer
// ---------------------------------------------------------------------------

void SerialConsole::_out(const char* str) {
    if (_captureBuffer) {
        *_captureBuffer += str;
    } else {
        Serial.print(str);
    }
}

void SerialConsole::_out(const String& str) {
    if (_captureBuffer) {
        *_captureBuffer += str;
    } else {
        Serial.print(str);
    }
}

void SerialConsole::_outln(const char* str) {
    if (_captureBuffer) {
        *_captureBuffer += str;
        *_captureBuffer += "\n";
    } else {
        Serial.println(str);
    }
}

void SerialConsole::_outln(const String& str) {
    if (_captureBuffer) {
        *_captureBuffer += str;
        *_captureBuffer += "\n";
    } else {
        Serial.println(str);
    }
}

void SerialConsole::_outln() {
    if (_captureBuffer) {
        *_captureBuffer += "\n";
    } else {
        Serial.println();
    }
}

// ---------------------------------------------------------------------------
// Main update loop — accumulate characters, process on newline
// ---------------------------------------------------------------------------

void SerialConsole::update() {
    while (Serial.available()) {
        char c = Serial.read();

        if (c == '\n' || c == '\r') {
            if (_inputBuffer.length() > 0) {
                Serial.println();
                _captureBuffer = nullptr;  // Serial commands go to Serial
                _processCommand(_inputBuffer);
                _inputBuffer = "";
                _printPrompt();
            }
        } else if (c == '\b' || c == 127) {
            if (_inputBuffer.length() > 0) {
                _inputBuffer.remove(_inputBuffer.length() - 1);
                Serial.print("\b \b");
            }
        } else {
            _inputBuffer += c;
            Serial.print(c);
        }
    }
}

// ---------------------------------------------------------------------------
// Command dispatch
// ---------------------------------------------------------------------------

void SerialConsole::_processCommand(const String& line) {
    String cmd = line;
    cmd.trim();
    if (cmd.length() == 0) return;

    if (cmd == "help" || cmd == "?") {
        _cmdHelp();
    } else if (cmd == "home") {
        _cmdHome();
    } else if (cmd == "where") {
        _cmdWhere();
    } else if (cmd == "joints") {
        _cmdJoints();
    } else if (cmd.startsWith("set ")) {
        _cmdSet(cmd.substring(4));
    } else if (cmd.startsWith("goto ")) {
        _cmdGoto(cmd.substring(5));
    } else if (cmd.startsWith("grip ")) {
        _cmdGrip(cmd.substring(5));
    } else if (cmd == "grip") {
        _outln("Usage: grip <angle>");
    } else if (cmd.startsWith("move ")) {
        _cmdMove(cmd.substring(5));
    } else if (cmd == "stop") {
        _cmdStop();
    } else if (cmd.startsWith("gesture ")) {
        _cmdGesture(cmd.substring(8));
    } else if (cmd == "gesture") {
        _outln("Usage: gesture <list|name> [stop|speed <v>]");
    } else if (cmd.startsWith("timed_set ")) {
        _cmdTimedSet(cmd.substring(10));
    } else if (cmd == "timed_set") {
        _outln("Usage: timed_set <base> <shoulder> <elbow> <grip> <time_ms>");
    } else if (cmd.startsWith("smset ")) {
        _cmdSmset(cmd.substring(6));
    } else if (cmd == "smset") {
        _outln("Usage: smset <joint> <angle>");
    } else if (cmd.startsWith("smparam ")) {
        _cmdSmparam(cmd.substring(8));
    } else if (cmd == "smparam") {
        _cmdSmparam("");
    } else if (cmd.startsWith("rawset ")) {
        _cmdRawset(cmd.substring(7));
    } else if (cmd == "rawset") {
        _outln("Usage: rawset <joint> <microseconds>");
    } else if (cmd.startsWith("test ")) {
        _cmdTest(cmd.substring(5));
    } else if (cmd == "test") {
        _outln("Usage: test <base|shoulder|elbow|grip|wave|all>");
    } else {
        _out("Unknown command: '");
        _out(cmd);
        _outln("'. Type 'help' for available commands.");
    }
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

void SerialConsole::_cmdHelp() {
    _outln("──────────────────────────────────────────");
    _outln("  Mira Console — Commands");
    _outln("──────────────────────────────────────────");
    _outln();
    _outln("  home                      Home all servos");
    _outln("  where                     Show position (x,y,z + grip)");
    _outln("  joints                    Show joint angles (base,shoulder,elbow,grip)");
    _outln();
    _outln("  ── Direct Control ──");
    _outln("  set <joint> <angle>       Set servo angle (0–180)");
    _outln("  goto <x> <y> <z>          Move to position (instant)");
    _outln("  grip <angle>              Set grip angle");
    _outln();
    _outln("  ── Smooth Motion ──");
    _outln("  move <x> <y> <z> [speed]  Move smoothly (mm/s)");
    _outln("  stop                      Stop all motion");
    _outln();
    _outln("  ── Gestures ──");
    _outln("  gesture list              List gestures");
    _outln("  gesture <name>            Start gesture");
    _outln("  gesture <name> stop       Stop gesture");
    _outln("  gesture <name> speed <v>  Set speed");
    _outln();
    _outln("  ── Smooth Joint Control ──");
    _outln("  smset <joint> <angle>     Smooth servo move");
    _outln("  timed_set B S E G <ms>   Timed move (all joints)");
    _outln("  smparam                   Show motion params");
    _outln("  smparam speed <v>         Max speed (deg/s)");
    _outln("  smparam accel <a>         Acceleration (deg/s²)");
    _outln();
    _outln("  ── Raw / Debug ──");
    _outln("  rawset <joint> <µs>        Set raw PWM pulse (0–20000)");
    _outln();
    _outln("  ── Servo Tests (blocking) ──");
    _outln("  test base|shoulder|elbow|grip|wave|all");
    _outln();
    _outln("  help                      Show this message");
    _outln("──────────────────────────────────────────");
}

void SerialConsole::_cmdHome() {
    _interruptMotion();
    _ctrl.home();

    float x, y, z;
    _ctrl.getPosition(x, y, z);

    String msg = "OK — homed (";
    msg += String(x, 1) + ", " + String(y, 1) + ", " + String(z, 1) + ")";
    _outln(msg);
}

void SerialConsole::_cmdWhere() {
    float x, y, z;
    _ctrl.getPosition(x, y, z);
    float grip = _ctrl.getGrip();

    String msg = "Position: X=" + String(x, 1) + " Y=" + String(y, 1) +
                 " Z=" + String(z, 1) + "  Grip=" + String(grip, 1);
    _outln(msg);

    if (_planner.isBusy()) {
        msg = "  Motion queue: " + String(_planner.queueSize()) + " waypoints";
        _outln(msg);
    }

    Gesture* active = _gestures.active();
    if (active) {
        msg = "  Active gesture: " + String(active->name());
        _outln(msg);
    }
}

void SerialConsole::_cmdJoints() {
    float base     = _ctrl.getJointAngle(SERVO_CH_BASE);
    float shoulder = _ctrl.getJointAngle(SERVO_CH_SHOULDER);
    float elbow    = _ctrl.getJointAngle(SERVO_CH_ELBOW);
    float grip     = _ctrl.getGrip();

    String msg = "Joints: Base=" + String(base, 1) + " Shoulder=" + String(shoulder, 1) +
                 " Elbow=" + String(elbow, 1) + " Grip=" + String(grip, 1);
    _outln(msg);
}

void SerialConsole::_cmdTimedSet(const String& args) {
    // Parse: "<base> <shoulder> <elbow> <grip> <time_ms>"
    float base, shoulder, elbow, grip;
    float timeF;

    String a = args;
    a.trim();

    int sp1 = a.indexOf(' ');
    if (sp1 < 0) { _outln("Usage: timed_set <base> <shoulder> <elbow> <grip> <time_ms>"); return; }
    int sp2 = a.indexOf(' ', sp1 + 1);
    if (sp2 < 0) { _outln("Usage: timed_set <base> <shoulder> <elbow> <grip> <time_ms>"); return; }
    int sp3 = a.indexOf(' ', sp2 + 1);
    if (sp3 < 0) { _outln("Usage: timed_set <base> <shoulder> <elbow> <grip> <time_ms>"); return; }
    int sp4 = a.indexOf(' ', sp3 + 1);
    if (sp4 < 0) { _outln("Usage: timed_set <base> <shoulder> <elbow> <grip> <time_ms>"); return; }

    String sBase     = a.substring(0, sp1);
    String sShoulder = a.substring(sp1 + 1, sp2);
    String sElbow    = a.substring(sp2 + 1, sp3);
    String sGrip     = a.substring(sp3 + 1, sp4);
    String sTime     = a.substring(sp4 + 1);

    if (!_parseFloat(sBase, base) || !_parseFloat(sShoulder, shoulder) ||
        !_parseFloat(sElbow, elbow) || !_parseFloat(sGrip, grip) ||
        !_parseFloat(sTime, timeF)) {
        _outln("Invalid arguments");
        return;
    }

    uint32_t timeMs = (uint32_t)timeF;
    if (timeMs < 50) {
        _outln("Time must be >= 50 ms");
        return;
    }

    _interruptMotion();

    _smooth.startTimedMove(base, shoulder, elbow, grip, timeMs);

    String msg = "OK — timed_set (" + String(base, 1) + ", " + String(shoulder, 1) +
                 ", " + String(elbow, 1) + ", " + String(grip, 1) + ") in " +
                 String(timeMs) + " ms";
    _outln(msg);
}

void SerialConsole::_cmdGoto(const String& args) {
    // Parse: "<x> <y> <z>"
    float x, y, z;
    int sp1 = args.indexOf(' ');
    if (sp1 < 0) { _outln("Usage: goto <x> <y> <z>"); return; }
    int sp2 = args.indexOf(' ', sp1 + 1);
    if (sp2 < 0) { _outln("Usage: goto <x> <y> <z>"); return; }

    String sx = args.substring(0, sp1);
    String sy = args.substring(sp1 + 1, sp2);
    String sz = args.substring(sp2 + 1);

    if (!_parseFloat(sx, x) || !_parseFloat(sy, y) || !_parseFloat(sz, z)) {
        _outln("Invalid coordinates");
        return;
    }

    _interruptMotion();

    if (_ctrl.moveTo(x, y, z)) {
        String msg = "OK — goto (" + String(x, 1) + ", " + String(y, 1) +
                     ", " + String(z, 1) + ")";
        _outln(msg);
    } else {
        _outln("ERROR — position unreachable (outside workspace or joint limits)");
    }
}

void SerialConsole::_cmdGrip(const String& args) {
    float angle;
    String str = args;
    str.trim();

    if (!_parseFloat(str, angle)) {
        _outln("Usage: grip <angle>");
        return;
    }

    _ctrl.setGrip(angle);
    String msg = "OK — grip → " + String(_ctrl.getGrip(), 1) + "°";
    _outln(msg);
}

void SerialConsole::_cmdMove(const String& args) {
    // Parse: "<x> <y> <z> [speed]"
    float x, y, z, speed = MOTION_DEFAULT_SPEED;

    int sp1 = args.indexOf(' ');
    if (sp1 < 0) { _outln("Usage: move <x> <y> <z> [speed]"); return; }
    int sp2 = args.indexOf(' ', sp1 + 1);
    if (sp2 < 0) { _outln("Usage: move <x> <y> <z> [speed]"); return; }

    String sx = args.substring(0, sp1);
    String sy = args.substring(sp1 + 1, sp2);

    // Check for optional speed parameter
    int sp3 = args.indexOf(' ', sp2 + 1);
    String sz, ss;
    if (sp3 > 0) {
        sz = args.substring(sp2 + 1, sp3);
        ss = args.substring(sp3 + 1);
        if (!_parseFloat(ss, speed)) {
            _outln("Invalid speed value");
            return;
        }
    } else {
        sz = args.substring(sp2 + 1);
    }

    if (!_parseFloat(sx, x) || !_parseFloat(sy, y) || !_parseFloat(sz, z)) {
        _outln("Invalid coordinates");
        return;
    }

    _interruptMotion();

    float grip = _ctrl.getGrip();
    if (_planner.enqueue(x, y, z, grip, speed)) {
        String msg = "OK — moving to (" + String(x, 1) + ", " + String(y, 1) +
                     ", " + String(z, 1) + ") at " + String(speed, 0) + " mm/s";
        _outln(msg);
    } else {
        _outln("ERROR — motion queue full");
    }
}

void SerialConsole::_cmdStop() {
    _interruptMotion();
    _outln("OK — stopped");
}

void SerialConsole::_cmdGesture(const String& args) {
    String input = args;
    input.trim();

    if (input == "list") {
        _outln("Available gestures:");
        for (uint8_t i = 0; i < _gestures.count(); i++) {
            Gesture* g = _gestures.get(i);
            String line = "  " + String(g->name());
            if (g->hasSpeed()) line += " (speed adjustable)";
            if (g->isRunning()) line += " [RUNNING]";
            _outln(line);
        }
        if (_gestures.count() == 0) {
            _outln("  (none registered)");
        }
        return;
    }

    // Parse: "<name> [stop|speed <v>]"
    int spaceIdx = input.indexOf(' ');
    String gestureName, subCmd;

    if (spaceIdx > 0) {
        gestureName = input.substring(0, spaceIdx);
        subCmd = input.substring(spaceIdx + 1);
        subCmd.trim();
    } else {
        gestureName = input;
    }

    Gesture* g = _gestures.find(gestureName.c_str());
    if (!g) {
        _out("Unknown gesture: '");
        _out(gestureName);
        _outln("'. Use 'gesture list'");
        return;
    }

    if (subCmd == "stop") {
        g->stop();
        _planner.clearQueue();
        String msg = "OK — " + gestureName + " stopped";
        _outln(msg);
    } else if (subCmd.startsWith("speed ")) {
        String speedStr = subCmd.substring(6);
        float speed;
        if (!_parseFloat(speedStr, speed)) {
            _outln("Usage: gesture <name> speed <value>");
            return;
        }
        if (!g->hasSpeed()) {
            _outln(gestureName + " does not support speed adjustment");
            return;
        }
        g->setSpeed(speed);
        String msg = "OK — " + gestureName + " speed → " + String(speed, 0) + " mm/s";
        _outln(msg);
    } else if (subCmd.length() == 0) {
        // Start the gesture
        _planner.clearQueue();
        _gestures.startGesture(gestureName.c_str());
    } else {
        _outln("Usage: gesture <name> [stop|speed <v>]");
    }
}

void SerialConsole::_cmdSet(const String& args) {
    int spaceIdx = args.indexOf(' ');
    if (spaceIdx < 0) {
        _outln("Usage: set <joint> <angle>");
        _outln("  Joints: base, shoulder, elbow, grip");
        return;
    }

    String jointName = args.substring(0, spaceIdx);
    String angleStr  = args.substring(spaceIdx + 1);
    jointName.trim();
    angleStr.trim();

    int channel = _resolveJoint(jointName);
    if (channel < 0) {
        _out("Unknown joint: '");
        _out(jointName);
        _outln("'. Use: base, shoulder, elbow, grip");
        return;
    }

    float angle;
    if (!_parseFloat(angleStr, angle)) {
        _out("Invalid angle: '");
        _out(angleStr);
        _outln("'");
        return;
    }

    if (angle < SERVO_ANGLE_MIN || angle > SERVO_ANGLE_MAX) {
        String msg = "Angle out of range (" + String(SERVO_ANGLE_MIN) +
                     "–" + String(SERVO_ANGLE_MAX) + ")";
        _outln(msg);
        return;
    }

    _ctrl.setJointAngle(channel, angle);
    String msg = "OK — " + jointName + " → " + String(angle, 1) + "°";
    _outln(msg);
}

void SerialConsole::_cmdTest(const String& args) {
    String testName = args;
    testName.trim();

    _interruptMotion();

    if (testName == "base")          _testBase();
    else if (testName == "shoulder") _testShoulder();
    else if (testName == "elbow")    _testElbow();
    else if (testName == "grip")     _testGrip();
    else if (testName == "wave")     _testCombinedWave();
    else if (testName == "all")      _testAll();
    else {
        _out("Unknown test: '");
        _out(testName);
        _outln("'. Use: base, shoulder, elbow, grip, wave, all");
    }
}

// ---------------------------------------------------------------------------
// Test routines (blocking — for servo-level debugging)
// ---------------------------------------------------------------------------

void SerialConsole::_testBase() {
    _outln("[Test] Base sweep");
    _arm.sweep(SERVO_CH_BASE, HOME_BASE, -50);
    _arm.sweep(SERVO_CH_BASE, -50, 50);
    _arm.sweep(SERVO_CH_BASE, 50, HOME_BASE);
    _outln("[Test] Base sweep complete");
}

void SerialConsole::_testShoulder() {
    _outln("[Test] Shoulder sweep");
    _arm.sweep(SERVO_CH_SHOULDER, HOME_SHOULDER, -45);
    _arm.sweep(SERVO_CH_SHOULDER, -45, 45);
    _arm.sweep(SERVO_CH_SHOULDER, 45, HOME_SHOULDER);
    _outln("[Test] Shoulder sweep complete");
}

void SerialConsole::_testElbow() {
    _outln("[Test] Elbow sweep");
    _arm.sweep(SERVO_CH_ELBOW, HOME_ELBOW, -45);
    _arm.sweep(SERVO_CH_ELBOW, -45, 45);
    _arm.sweep(SERVO_CH_ELBOW, 45, HOME_ELBOW);
    _outln("[Test] Elbow sweep complete");
}

void SerialConsole::_testGrip() {
    _outln("[Test] Grip open/close");
    _arm.openGrip();
    delay(TEST_PAUSE_MS);
    _arm.closeGrip();
    delay(TEST_PAUSE_MS);
    _arm.setGrip(HOME_GRIP);
    _outln("[Test] Grip test complete");
}

void SerialConsole::_testCombinedWave() {
    _outln("[Test] Combined wave");
    for (float offset = 0; offset <= 40; offset += 2) {
        _arm.setBase(HOME_BASE - offset);
        _arm.setShoulder(HOME_SHOULDER + offset);
        delay(TEST_STEP_DELAY_MS);
    }
    for (float offset = 40; offset >= -40; offset -= 2) {
        _arm.setBase(HOME_BASE - offset);
        _arm.setShoulder(HOME_SHOULDER + offset);
        delay(TEST_STEP_DELAY_MS);
    }
    for (float offset = -40; offset <= 0; offset += 2) {
        _arm.setBase(HOME_BASE - offset);
        _arm.setShoulder(HOME_SHOULDER + offset);
        delay(TEST_STEP_DELAY_MS);
    }
    _outln("[Test] Combined wave complete");
}

void SerialConsole::_testAll() {
    _outln("[Test] Running all tests...");
    _outln();
    _testBase();    delay(TEST_PAUSE_MS);
    _testShoulder(); delay(TEST_PAUSE_MS);
    _testElbow();   delay(TEST_PAUSE_MS);
    _testGrip();    delay(TEST_PAUSE_MS);
    _testCombinedWave();
    _outln();
    _arm.home();
    _outln("[Test] All tests complete — homed");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

void SerialConsole::_printPrompt() {
    Serial.print("mira> ");
}

int SerialConsole::_resolveJoint(const String& name) {
    if (name == "base")     return SERVO_CH_BASE;
    if (name == "shoulder") return SERVO_CH_SHOULDER;
    if (name == "elbow")    return SERVO_CH_ELBOW;
    if (name == "grip")     return SERVO_CH_GRIP;
    return -1;
}

bool SerialConsole::_parseFloat(const String& str, float& value) {
    if (str.length() == 0) return false;

    // Check for valid numeric characters (allow leading minus, digits, dot)
    char first = str.charAt(0);
    if (first != '-' && first != '.' && (first < '0' || first > '9')) {
        return false;
    }

    value = str.toFloat();

    // toFloat returns 0.0 for non-numeric; disambiguate from actual "0"
    if (value == 0.0f && str != "0" && str != "0.0" && str != "-0" && !str.startsWith("0.") && !str.startsWith("-0.")) {
        return false;
    }

    return true;
}

void SerialConsole::_cmdSmset(const String& args) {
    // Parse: "<joint> <angle>"
    int spaceIdx = args.indexOf(' ');
    if (spaceIdx < 0) {
        _outln("Usage: smset <joint> <angle>");
        _outln("  Joints: base, shoulder, elbow, grip");
        return;
    }

    String jointName = args.substring(0, spaceIdx);
    String angleStr  = args.substring(spaceIdx + 1);
    jointName.trim();
    angleStr.trim();

    int channel = _resolveJoint(jointName);
    if (channel < 0) {
        _out("Unknown joint: '");
        _out(jointName);
        _outln("'. Use: base, shoulder, elbow, grip");
        return;
    }

    float angle;
    if (!_parseFloat(angleStr, angle)) {
        _out("Invalid angle: '");
        _out(angleStr);
        _outln("'");
        return;
    }

    if (angle < SERVO_ANGLE_MIN || angle > SERVO_ANGLE_MAX) {
        String msg = "Angle out of range (" + String(SERVO_ANGLE_MIN) +
                     "–" + String(SERVO_ANGLE_MAX) + ")";
        _outln(msg);
        return;
    }

    _smooth.startMove(channel, angle);
    String msg = "OK — smooth " + jointName + " → " + String(angle, 1) + "° (" +
                 String(_smooth.getMaxSpeed(), 0) + " deg/s, " +
                 String(_smooth.getAcceleration(), 0) + " deg/s²)";
    _outln(msg);
}

void SerialConsole::_cmdSmparam(const String& args) {
    String input = args;
    input.trim();

    if (input.length() == 0) {
        // Show current parameters
        _outln("Smooth motion parameters:");
        String msg = "  Max speed:     " + String(_smooth.getMaxSpeed(), 1) + " deg/s";
        _outln(msg);
        msg = "  Acceleration:  " + String(_smooth.getAcceleration(), 1) + " deg/s²";
        _outln(msg);
        return;
    }

    int spaceIdx = input.indexOf(' ');
    if (spaceIdx < 0) {
        _outln("Usage: smparam speed <v> | smparam accel <a>");
        return;
    }

    String param = input.substring(0, spaceIdx);
    String valStr = input.substring(spaceIdx + 1);
    param.trim();
    valStr.trim();

    float value;
    if (!_parseFloat(valStr, value) || value <= 0) {
        _outln("Value must be a positive number");
        return;
    }

    if (param == "speed") {
        _smooth.setMaxSpeed(value);
        String msg = "OK — max speed → " + String(value, 1) + " deg/s";
        _outln(msg);
    } else if (param == "accel") {
        _smooth.setAcceleration(value);
        String msg = "OK — acceleration → " + String(value, 1) + " deg/s²";
        _outln(msg);
    } else {
        _out("Unknown parameter: '");
        _out(param);
        _outln("'. Use: speed, accel");
    }
}

void SerialConsole::_cmdRawset(const String& args) {
    int spaceIdx = args.indexOf(' ');
    if (spaceIdx < 0) {
        _outln("Usage: rawset <joint> <microseconds>");
        _outln("  Joints: base, shoulder, elbow, grip");
        _outln("  Range:  0–20000 µs (center ≈ 1500)");
        return;
    }

    String jointName = args.substring(0, spaceIdx);
    String usStr     = args.substring(spaceIdx + 1);
    jointName.trim();
    usStr.trim();

    int channel = _resolveJoint(jointName);
    if (channel < 0) {
        _out("Unknown joint: '");
        _out(jointName);
        _outln("'. Use: base, shoulder, elbow, grip");
        return;
    }

    float usFloat;
    if (!_parseFloat(usStr, usFloat) || usFloat < 0) {
        _out("Invalid pulse: '");
        _out(usStr);
        _outln("'");
        return;
    }

    uint16_t pulseUs = (uint16_t)usFloat;
    if (pulseUs > 20000) pulseUs = 20000;

    _arm.setServoRawUs(channel, pulseUs);
    String msg = "OK — " + jointName + " → " + String(pulseUs) +
                 " µs (tick " + String((uint16_t)(pulseUs * 4096.0f / 20000.0f)) + ")";
    _outln(msg);
}

void SerialConsole::_interruptMotion() {
    _gestures.stopAll();
    _planner.clearQueue();
    _smooth.stopAll();
}
