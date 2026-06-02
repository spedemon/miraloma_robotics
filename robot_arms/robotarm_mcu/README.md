# Mira Robot Arm MCU Firmware

Firmware for the Mira robot arm controller. Runs on an **ESP32-C3 Super Mini** and drives 4 servos through a **PCA9685** I2C PWM driver.

## Hardware Connections

### ESP32-C3 → PCA9685

| Signal | ESP32-C3 GPIO | PCA9685 Pin |
|--------|--------------|-------------|
| SDA    | 6            | SDA         |
| SCL    | 7            | SCL         |
| VCC    | 3.3V         | VCC         |
| GND    | GND          | GND         |

> **Note:** The PCA9685 V+ terminal should be connected to an external 5–6V power supply rated for the servo current draw — do **not** power servos from the ESP32-C3.

### PCA9685 → Servos

| Servo    | PCA9685 Channel | Axis     | Function                    |
|----------|----------------|----------|-----------------------------|
| Grip     | 0              | —        | Open / close gripper        |
| Base     | 1              | Vertical | Rotate arm left / right     |
| Shoulder | 2              | Horizontal | Lower arm joint (up/down) |
| Elbow    | 3              | Horizontal | Upper arm joint (up/down) |

## Configuration

All hardware settings are centralized in [`include/config.h`](include/config.h):
- I2C pins
- PCA9685 address and PWM frequency
- Servo channel assignments
- Pulse width ranges
- Angle limits
- Home positions
- Grip presets
- Test timing

## Build & Flash

Requires [PlatformIO](https://platformio.org/).

```bash
# Build
cd robotarm_mcu
pio run

# Build + upload + serial monitor
pio run -t upload -t monitor
```

## Test Routine

On boot, the firmware runs a continuous test loop:

1. **Base sweep** — rotates left, then right, then home
2. **Shoulder sweep** — raises up, then down, then home
3. **Elbow sweep** — bends up, then down, then home
4. **Grip test** — open, close, then home
5. **Combined wave** — base and shoulder move together in a wave pattern
6. **Home + pause** — returns to center, pauses, then repeats

Serial output logs each phase for debugging.

