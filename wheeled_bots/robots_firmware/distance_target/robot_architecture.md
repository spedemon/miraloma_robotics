# Distance-to-Target System — Architecture

## Identity
- **Name:** Distance-to-Target
- **Type:** Two-node distance measurement accessory (not a standalone robot)
- **Home:** Miraloma Elementary School
- **Purpose:** Provides centimeter-level distance measurement between a robot and a target beacon using ultrasonic time-of-flight synchronized over radio.

## Physical Description
The system consists of **two identical hardware nodes**, each built from an ESP32 DevKit and an HY-SRF05 ultrasonic sensor module:

- **Node A — Initiator:** Mounted on the robot. Sends the ultrasonic pulse and an ESP-NOW radio sync simultaneously.
- **Node B — Responder:** Placed at the target location. Times the sound arrival and computes the distance.

Each node is a small breadboard assembly (~$7 per node, ~$14 total).

## How It Works

The system exploits the speed difference between **radio waves** (~300,000 km/s, effectively instant) and **sound** (~343 m/s):

1. The Initiator fires a 10 µs trigger pulse on its HY-SRF05 and broadcasts an ESP-NOW sync packet.
2. The Responder receives the radio packet instantly (Start Time) and waits for the ultrasonic pulse to arrive at its Echo pin (End Time).
3. Distance = (End Time − Start Time) × 0.0343 cm/µs.
4. The Responder sends the result back to the Initiator via ESP-NOW.

## Capabilities

### Distance Measurement
- **Range:** 2 cm to ~4.5–5.0 m (limited by sound attenuation)
- **Resolution:** ~3 mm (dependent on ESP32 timer precision)
- **Update rate:** 10–20 Hz (configurable via UART `RATE:<hz>` command)
- **Accuracy:** Centimeter-level under normal indoor conditions

### Communication
- **Between nodes:** ESP-NOW (2.4 GHz peer-to-peer, no Wi-Fi AP required)
- **To host:** Serial UART at 115200 baud
- **Output format:** `DIST: <value> cm` and `STATUS: ENABLED / DISABLED`

### UART Commands
| Command | Description |
|---------|-------------|
| `EN`    | Enable active measurement |
| `DIS`   | Disable measurement / low-power mode |
| `GET`   | Request the last recorded distance |
| `RATE:<hz>` | Set update rate (Initiator only) |

## Hardware Requirements

| Component | Qty | Notes |
|-----------|-----|-------|
| ESP32 DevKit (or ESP8266 NodeMCU) | 2 | One per node |
| HY-SRF05 Ultrasonic Module | 2 | One per node |
| Voltage divider resistors (1 kΩ + 2 kΩ) | 2 sets | Echo pin: 5 V → 3.3 V level shift |
| Breadboard + jumper wires | — | For prototyping |
| USB cables | 2 | For flashing and UART |

## Limitations
- **Maximum range ~5 m** — ultrasonic pulses attenuate beyond this distance
- **Line-of-sight required** — sound must travel unobstructed between nodes
- **Temperature dependent** — speed of sound varies with air temperature (~0.6 m/s per °C)
- **Not a robot** — this system does not have motors, wheels, or actuators; it only measures distance
- **Single-axis** — measures distance only, not direction or bearing
- **Interference** — other ultrasonic sources (e.g., the Mecanum robot's own sensor) may cause false readings if active simultaneously
