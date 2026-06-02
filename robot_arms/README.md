# 🦾 Robot Arms

> Part of [Miraloma Robotics](../README.md)

> **Mira** — an educational robot arm platform for elementary school kids. Control one arm or a whole swarm from a sleek web interface.

[![PlatformIO](https://img.shields.io/badge/PlatformIO-ESP32--C3-FF7F00?logo=platformio&logoColor=white)](https://platformio.org)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)

---

## ✨ What Is This?

Mira is a **3-DOF robot arm** with 4 servos (base, shoulder, elbow, grip) driven by a **PCA9685** PWM driver on an **ESP32-C3 Super Mini**. Multiple arms communicate wirelessly via **ESP-NOW** (peer-to-peer radio, no Wi-Fi router needed), forming a swarm coordinated through a USB bridge.

A web interface provides real-time control with joint sliders, Cartesian (IK) positioning, a keyframe sequencer, and built-in gesture triggers — perfect for classroom demos and choreographed performances.

---

## 📂 Project Structure

```
robot_arms/
├── robotarm_mcu/    # Firmware for each robot arm (ESP32-C3 Super Mini)
├── master_mcu/      # Firmware for the USB bridge / swarm coordinator (ESP32-C3)
└── web_app/         # Web UI + Python server (Flask + SocketIO)
    ├── mira.py          # Backend server
    ├── static/          # Frontend (HTML, CSS, JS)
    └── robot_names.json # Persistent robot display names
```

---

## 🚀 Quick Start

### Prerequisites

- [PlatformIO CLI](https://platformio.org/install/cli) — for building & flashing firmware
- Python 3.10+ — for the web server
- Two ESP32-C3 boards connected via USB

### 1. Flash the Robot Arm

```bash
cd robot_arms/robotarm_mcu
./build.sh
./flash.sh /dev/tty.usbmodemXXXX   # or let it auto-detect
```

### 2. Flash the Master (Swarm Coordinator)

```bash
cd robot_arms/master_mcu
./build.sh
./flash.sh /dev/tty.usbmodemYYYY
```

### 3. Start the Web UI

```bash
cd robot_arms/web_app
pip install -r requirements.txt
python3 mira.py
```

Open **http://localhost:5000** in your browser. Click the serial badge in the header to connect to the master's USB port. Any powered-on robot arms will appear in the swarm panel within a few seconds.

---

## 🔧 Hardware Overview

Mira is a 3-DOF robot arm with 4 servos:

| Servo      | Axis       | Function                  |
|------------|------------|---------------------------|
| **Base**   | Vertical   | Rotates arm left / right  |
| **Shoulder** | Horizontal | Lower arm joint (up/down) |
| **Elbow**  | Horizontal | Upper arm joint (up/down) |
| **Grip**   | —          | Opens / closes gripper    |

Servos are driven by a **PCA9685** 16-channel PWM driver, connected to the ESP32-C3 via I2C. The master and robot arm nodes communicate wirelessly over **ESP-NOW** (peer-to-peer radio, no Wi-Fi router needed).

---

## 🏗️ Architecture

```
┌─────────────┐   USB Serial   ┌─────────────┐   ESP-NOW   ┌──────────────┐
│   Browser   │ ◄────────────► │   Master    │ ◄─────────► │  Robot Arm 1 │
│  (Web UI)   │   WebSocket    │   MCU       │             ├──────────────┤
│             │ ◄────────────► │             │ ◄─────────► │  Robot Arm 2 │
│             │                │             │             ├──────────────┤
│             │   Flask +      │  ESP32-C3   │   Broadcast │  Robot Arm N │
│             │   SocketIO     │             │             └──────────────┘
└─────────────┘                └─────────────┘
     mira.py                    master_mcu/                 robotarm_mcu/
```

- **Robot Arm MCU** — drives servos, runs motion planner & gestures, broadcasts heartbeat
- **Master MCU** — USB ↔ ESP-NOW bridge, tracks which arms are online, routes commands
- **Web Server** (`mira.py`) — bridges browser ↔ master serial, manages persistent state
- **Web UI** — real-time swarm panel, joint/Cartesian sliders, sequencer, gesture triggers

---

## 🎮 Features

- **Joint Control** — individual sliders for base, shoulder, elbow, grip
- **Cartesian Control** — X/Y/Z sliders with real-time inverse kinematics
- **Keyframe Sequencer** — record, edit, and play back choreographed motions
- **Gestures** — built-in animations: dance, bow, wave, draw shapes (circle, square, triangle)
- **Swarm Panel** — discover, rename, and control multiple arms simultaneously
- **Serial Console** — debug commands via the master MCU

### Serial Console Commands

```
swarm list              # Show all discovered robots and their status
swarm rename R1 Lefty   # Give a robot a friendly name
move R1 j1 45           # Move a specific joint
ping                    # Test connectivity
```

---

## ⚙️ Configuration

- **Robot arm hardware** — [`robotarm_mcu/include/config.h`](robotarm_mcu/include/config.h) (servo channels, PWM ranges, angle limits, IK geometry)
- **Master timing** — [`master_mcu/include/config.h`](master_mcu/include/config.h) (heartbeat timeout, swarm settings)
- **Web server** — [`web_app/mira.py`](web_app/mira.py) (baud rate, poll interval)

---

## 🤝 Contributing

See the [monorepo contributing guide](../README.md#-contributing) for general guidelines.

### Development

```bash
cd miraloma_robotics/robot_arms/web_app
pip install -r requirements.txt
python3 mira.py
```

For firmware development, use PlatformIO:

```bash
cd robotarm_mcu   # or master_mcu
pio run                        # Build
pio run -t upload -t monitor   # Build + flash + serial monitor
```

---

## 📜 License

This project is open source and available under the [MIT License](../LICENSE).
