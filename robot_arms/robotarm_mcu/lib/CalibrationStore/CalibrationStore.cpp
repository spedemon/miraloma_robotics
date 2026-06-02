/**
 * CalibrationStore.cpp — Per-Joint Servo Calibration Offsets
 *
 * Uses the ESP32 Preferences library (NVS flash) to persist
 * calibration offsets across power cycles.
 */

#include "CalibrationStore.h"
#include <Preferences.h>

// NVS namespace and key names (kept short for NVS efficiency)
static const char* NVS_NAMESPACE = "mira_cal";
static const char* KEY_BASE     = "base";
static const char* KEY_SHOULDER = "shldr";
static const char* KEY_ELBOW    = "elbow";
static const char* KEY_GRIP     = "grip";

CalibrationStore::CalibrationStore() {
    for (int i = 0; i < 4; i++) _offsets[i] = 0.0f;
}

void CalibrationStore::begin() {
    _load();

    Serial.println("[CalStore] Calibration offsets loaded:");
    Serial.print("  Base=");     Serial.print(_offsets[SERVO_CH_BASE], 1);
    Serial.print("  Shoulder="); Serial.print(_offsets[SERVO_CH_SHOULDER], 1);
    Serial.print("  Elbow=");    Serial.print(_offsets[SERVO_CH_ELBOW], 1);
    Serial.print("  Grip=");     Serial.println(_offsets[SERVO_CH_GRIP], 1);
}

float CalibrationStore::getOffset(uint8_t channel) const {
    if (channel >= 4) return 0.0f;
    return _offsets[channel];
}

void CalibrationStore::setOffsets(float base, float shoulder, float elbow, float grip) {
    _offsets[SERVO_CH_BASE]     = base;
    _offsets[SERVO_CH_SHOULDER] = shoulder;
    _offsets[SERVO_CH_ELBOW]    = elbow;
    _offsets[SERVO_CH_GRIP]     = grip;
    _save();
}

void CalibrationStore::resetOffsets() {
    for (int i = 0; i < 4; i++) _offsets[i] = 0.0f;

    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, false);  // read-write
    prefs.clear();
    prefs.end();

    Serial.println("[CalStore] Calibration reset to zero");
}

void CalibrationStore::getOffsets(float& base, float& shoulder, float& elbow, float& grip) const {
    base     = _offsets[SERVO_CH_BASE];
    shoulder = _offsets[SERVO_CH_SHOULDER];
    elbow    = _offsets[SERVO_CH_ELBOW];
    grip     = _offsets[SERVO_CH_GRIP];
}

void CalibrationStore::_save() {
    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, false);  // read-write
    prefs.putFloat(KEY_BASE,     _offsets[SERVO_CH_BASE]);
    prefs.putFloat(KEY_SHOULDER, _offsets[SERVO_CH_SHOULDER]);
    prefs.putFloat(KEY_ELBOW,    _offsets[SERVO_CH_ELBOW]);
    prefs.putFloat(KEY_GRIP,     _offsets[SERVO_CH_GRIP]);
    prefs.end();
}

void CalibrationStore::_load() {
    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, true);  // read-only
    _offsets[SERVO_CH_BASE]     = prefs.getFloat(KEY_BASE,     0.0f);
    _offsets[SERVO_CH_SHOULDER] = prefs.getFloat(KEY_SHOULDER, 0.0f);
    _offsets[SERVO_CH_ELBOW]    = prefs.getFloat(KEY_ELBOW,    0.0f);
    _offsets[SERVO_CH_GRIP]     = prefs.getFloat(KEY_GRIP,     0.0f);
    prefs.end();
}
