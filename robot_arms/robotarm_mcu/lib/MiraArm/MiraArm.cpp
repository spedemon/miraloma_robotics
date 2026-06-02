/**
 * MiraArm.cpp — Mira Robot Arm Controller Implementation
 */

#include "MiraArm.h"

MiraArm::MiraArm()
    : _pca(PCA9685_ADDR) {
}

void MiraArm::begin() {
    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(400000);  // I2C fast mode — 4× faster servo writes
    _pca.begin();
    _pca.setPWMFreq(PCA9685_FREQ);
    delay(10);  // Let the oscillator stabilize

    Serial.println("[MiraArm] PCA9685 initialized");
    Serial.print("[MiraArm] I2C SDA=");
    Serial.print(PIN_SDA);
    Serial.print(" SCL=");
    Serial.println(PIN_SCL);
    Serial.print("[MiraArm] PWM freq=");
    Serial.print(PCA9685_FREQ);
    Serial.println(" Hz");
}

// ---------------------------------------------------------------------------
// Per-channel servo calibration table
// ---------------------------------------------------------------------------

struct ServoCalibration {
    float   loDeg;      // Low  reference angle (degrees)
    float   loUs;       // Low  reference pulse (µs)
    float   hiDeg;      // High reference angle (degrees)
    float   hiUs;       // High reference pulse (µs)
    float   pulseMin;   // Hard minimum pulse (µs)
    float   pulseMax;   // Hard maximum pulse (µs)
};

// Indexed by PCA9685 channel — order must match SERVO_CH_* defines.
// Channels beyond ELBOW (3) fall back to the first entry.
static const ServoCalibration CAL[] = {
    // CH 0: Grip
    { SERVO_GRIP_CAL_LO_DEG,     SERVO_GRIP_CAL_LO_US,
      SERVO_GRIP_CAL_HI_DEG,     SERVO_GRIP_CAL_HI_US,
      SERVO_GRIP_PULSE_MIN,      SERVO_GRIP_PULSE_MAX },
    // CH 1: Base
    { SERVO_BASE_CAL_LO_DEG,     SERVO_BASE_CAL_LO_US,
      SERVO_BASE_CAL_HI_DEG,     SERVO_BASE_CAL_HI_US,
      SERVO_BASE_PULSE_MIN,      SERVO_BASE_PULSE_MAX },
    // CH 2: Shoulder
    { SERVO_SHOULDER_CAL_LO_DEG, SERVO_SHOULDER_CAL_LO_US,
      SERVO_SHOULDER_CAL_HI_DEG, SERVO_SHOULDER_CAL_HI_US,
      SERVO_SHOULDER_PULSE_MIN,  SERVO_SHOULDER_PULSE_MAX },
    // CH 3: Elbow
    { SERVO_ELBOW_CAL_LO_DEG,    SERVO_ELBOW_CAL_LO_US,
      SERVO_ELBOW_CAL_HI_DEG,    SERVO_ELBOW_CAL_HI_US,
      SERVO_ELBOW_PULSE_MIN,     SERVO_ELBOW_PULSE_MAX },
};
static const int CAL_COUNT = sizeof(CAL) / sizeof(CAL[0]);

// ---------------------------------------------------------------------------
// Angle → PCA9685 tick conversion (per-channel calibration)
// ---------------------------------------------------------------------------

uint16_t MiraArm::_angleToTick(uint8_t channel, float angle) {
    const ServoCalibration& c = CAL[channel < CAL_COUNT ? channel : 0];

    // Linear map: angle → pulse µs using two reference points
    float usPerDeg = (c.hiUs - c.loUs) / (c.hiDeg - c.loDeg);
    float pulseUs  = c.loUs + (angle - c.loDeg) * usPerDeg;

    // Clamp to physical pulse limits
    if (pulseUs < c.pulseMin) pulseUs = c.pulseMin;
    if (pulseUs > c.pulseMax) pulseUs = c.pulseMax;

    // Convert µs to PCA9685 tick (dynamic based on PCA9685_FREQ)
    float periodUs = 1000000.0f / PCA9685_FREQ;
    uint16_t tick = (uint16_t)(pulseUs * 4096.0f / periodUs);
    return tick;
}

// ---------------------------------------------------------------------------
// Core servo control
// ---------------------------------------------------------------------------

void MiraArm::setServoAngle(uint8_t channel, float angle) {
    uint16_t tick = _angleToTick(channel, angle);
    _pca.setPWM(channel, 0, tick);
}

void MiraArm::setServoRawUs(uint8_t channel, uint16_t pulseUs) {
    float periodUs = 1000000.0f / PCA9685_FREQ;
    if (pulseUs > (uint16_t)periodUs) pulseUs = (uint16_t)periodUs;
    uint16_t tick = (uint16_t)((float)pulseUs * 4096.0f / periodUs);
    if (tick > 4095) tick = 4095;
    _pca.setPWM(channel, 0, tick);
}

// ---------------------------------------------------------------------------
// Named setters
// ---------------------------------------------------------------------------

void MiraArm::setGrip(float angle)     { setServoAngle(SERVO_CH_GRIP, angle); }
void MiraArm::setBase(float angle)     { setServoAngle(SERVO_CH_BASE, angle); }
void MiraArm::setShoulder(float angle) { setServoAngle(SERVO_CH_SHOULDER, angle); }
void MiraArm::setElbow(float angle)    { setServoAngle(SERVO_CH_ELBOW, angle); }

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

void MiraArm::home() {
    Serial.println("[MiraArm] Homing all servos");
    setGrip(HOME_GRIP);
    setBase(HOME_BASE);
    setShoulder(HOME_SHOULDER);
    setElbow(HOME_ELBOW);
}

void MiraArm::openGrip() {
    Serial.println("[MiraArm] Grip OPEN");
    setGrip(GRIP_OPEN_ANGLE);
}

void MiraArm::closeGrip() {
    Serial.println("[MiraArm] Grip CLOSED");
    setGrip(GRIP_CLOSED_ANGLE);
}

// ---------------------------------------------------------------------------
// Sweep (blocking — for test routines)
// ---------------------------------------------------------------------------

void MiraArm::sweep(uint8_t channel, float fromAngle, float toAngle, uint16_t stepDelay) {
    float step = (toAngle > fromAngle) ? 1.0f : -1.0f;
    float angle = fromAngle;

    while (true) {
        setServoAngle(channel, angle);
        delay(stepDelay);

        if ((step > 0 && angle >= toAngle) || (step < 0 && angle <= toAngle)) {
            break;
        }
        angle += step;
    }
}
