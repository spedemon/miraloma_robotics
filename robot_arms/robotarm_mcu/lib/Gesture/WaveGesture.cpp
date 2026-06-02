/**
 * WaveGesture.cpp — Sinusoidal wave with slow base sweep
 *
 * Creates a wave-like motion using shoulder and elbow oscillating
 * with a 90° phase offset (shoulder leads, elbow follows). The
 * small amplitude keeps the motion gentle and wave-like.
 *
 * Meanwhile, the base sweeps slowly — at 1/10 the wave frequency —
 * panning the wave across a full sweep: 0° → +80° → -80° → 0° ...
 *
 * The amplitude ramps up smoothly over the first wave period to
 * avoid any snap from home position.
 *
 * Speed control scales the wave frequency (default 75 mm/s = 1.5 Hz).
 */

#include "WaveGesture.h"
#include "config.h"
#include <math.h>

// --- Wave parameters ---

// Amplitude of the oscillation (degrees) — kept small for a gentle wave
static const float SHOULDER_AMP = 12.0f;
static const float ELBOW_AMP    = 18.0f;

// Base sweep range (degrees)
static const float BASE_AMP = 80.0f;

// Wave frequency at default speed (Hz)
// 1.5 Hz ≈ one full wave cycle every 667ms
static const float BASE_WAVE_FREQ = 1.5f;

// Base rotates at 1/10 the wave frequency
static const float BASE_FREQ_RATIO = 0.1f;

// Ramp-up time: amplitude grows from 0 to full over this period (ms)
static const uint32_t RAMP_MS = 800;

// Update throttle
static const uint32_t TICK_MS = 5;  // ~200 Hz


WaveGesture::WaveGesture(MotionPlanner& planner, ArmController& ctrl)
    : _planner(planner), _ctrl(ctrl),
      _running(false), _speed(75.0f), _startMs(0), _lastTickMs(0) {
}

void WaveGesture::start() {
    _running = true;
    _planner.clearQueue();
    _startMs = millis();
    _lastTickMs = _startMs;
    Serial.println("[Gesture] Wave started");
}

void WaveGesture::stop() {
    _running = false;
    _planner.clearQueue();
    _ctrl.home();
    Serial.println("[Gesture] Wave stopped");
}

void WaveGesture::update() {
    if (!_running) return;

    uint32_t now = millis();
    if (now - _lastTickMs < TICK_MS) return;
    _lastTickMs = now;

    // Elapsed time in seconds
    float elapsed = (now - _startMs) / 1000.0f;

    // Scale wave frequency by speed (speed=75 → freq=1.5 Hz)
    float waveFreq = BASE_WAVE_FREQ * (_speed / 75.0f);
    float baseFreq = waveFreq * BASE_FREQ_RATIO;

    // Angular velocities (rad/s)
    float omegaWave = 2.0f * M_PI * waveFreq;
    float omegaBase = 2.0f * M_PI * baseFreq;

    // Smooth amplitude ramp-up (0 → 1 over RAMP_MS)
    float ramp = (now - _startMs) < RAMP_MS
               ? (float)(now - _startMs) / (float)RAMP_MS
               : 1.0f;

    // Wave motion: shoulder leads, elbow follows with 90° phase offset
    float shoulderAngle = ramp * SHOULDER_AMP * sinf(omegaWave * elapsed);
    float elbowAngle    = ramp * ELBOW_AMP    * sinf(omegaWave * elapsed + M_PI / 2.0f);

    // Slow base sweep: sinusoidal at 1/10 wave frequency
    float baseAngle = ramp * BASE_AMP * sinf(omegaBase * elapsed);

    // Apply joint angles directly
    _ctrl.setJointAngle(SERVO_CH_BASE, baseAngle);
    _ctrl.setJointAngle(SERVO_CH_SHOULDER, shoulderAngle);
    _ctrl.setJointAngle(SERVO_CH_ELBOW, elbowAngle);
}

bool WaveGesture::isRunning() { return _running; }
void WaveGesture::setSpeed(float speed) { _speed = speed; }
