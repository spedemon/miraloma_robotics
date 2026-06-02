# 🤖 Miraloma Robotics

> **Building, programming, and talking to real robots — at Miraloma Elementary School.**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![PlatformIO](https://img.shields.io/badge/PlatformIO-ESP32-FF7F00?logo=platformio&logoColor=white)](https://platformio.org)
[![Gemini AI](https://img.shields.io/badge/Google%20Gemini-AI-A855F7?logo=google&logoColor=white)](https://ai.google.dev)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

Miraloma Robotics is a collection of open-source robotics projects designed for elementary school kids. Students build real robots, flash custom firmware, and control them through beautiful web interfaces — using sliders, voice commands, or plain-English conversations powered by Google Gemini AI.

This monorepo contains two independent projects that share a common mission: **making robotics accessible, fun, and educational**.

---

## 📦 Projects

<table>
<tr>
<td width="50%" valign="top">

### 🦾 [Robot Arms](robot_arms/)

A swarm of 3-DOF robot arms built with **SG90 servo motors** and **ESP32-C3** microcontrollers. Control one arm or an entire swarm from a sleek web interface.

**Highlights:**
- 🎯 Joint & Cartesian (IK) control with real-time sliders
- 🎬 Keyframe sequencer for choreographed motions
- 💃 Built-in gestures — dance, bow, wave, draw shapes
- 📡 Wireless swarm control via **ESP-NOW** (no Wi-Fi needed)
- 🔌 USB bridge for browser ↔ swarm communication

**Tech:** ESP32-C3 · PCA9685 PWM · PlatformIO · Flask + SocketIO

</td>
<td width="50%" valign="top">

### 🚗 [Wheeled Bots](wheeled_bots/)

AI-powered wheeled and walking robots that kids control by **talking**. Speak a command, and Google Gemini generates Python code in real-time to drive the robot.

**Highlights:**
- 🗣️ Voice & text chat — *"move forward 3 feet"*
- 🧠 AI code generation — Gemini writes & runs Python on the fly
- 🤖 Multi-robot support — Mecanum car & Spider walker
- 🎨 Animated robot face that reacts to state
- 📡 Autonomous navigation with ultrasonic distance-to-target

**Tech:** NiceGUI · Google Gemini · Micro:bit · ESP8266 · pyserial

</td>
</tr>
</table>

---

## 🚀 Getting Started

Each project is self-contained with its own firmware, web UI, and documentation. Pick the one you're working with:

| Project | Quick Start | Prerequisites |
|---------|------------|---------------|
| **🦾 Robot Arms** | [`robot_arms/README.md`](robot_arms/README.md) | PlatformIO, Python 3.10+, ESP32-C3 boards |
| **🚗 Wheeled Bots** | [`wheeled_bots/README.md`](wheeled_bots/README.md) | Python 3.10+, Gemini API key, USB robot |

---

## 🏗️ Repository Structure

```
miraloma_robotics/
├── robot_arms/              # 🦾 Servo-based robot arm swarm
│   ├── robotarm_mcu/        #    Firmware for each arm (ESP32-C3)
│   ├── master_mcu/          #    USB bridge / swarm coordinator
│   └── web_app/             #    Web UI + Python server
├── wheeled_bots/            # 🚗 AI-powered wheeled & walking robots
│   ├── robots_firmware/     #    Firmware for Mecanum car & Spider
│   ├── static/              #    Web UI assets
│   └── *.py                 #    Python backend (NiceGUI + Gemini)
├── README.md                # ← You are here
└── .gitignore
```

---

## 🤝 Contributing

We welcome contributions from parents, teachers, students, and fellow robotics enthusiasts!

- **Robot Arms** — See [contributing in robot_arms](robot_arms/README.md#development)
- **Wheeled Bots** — See [contributing in wheeled_bots](wheeled_bots/README.md#-contributing)

### General Guidelines

1. Fork the repo and create a feature branch
2. Make your changes in the appropriate project directory
3. Test with real hardware when possible
4. Submit a pull request with a clear description

---

## 📜 License

This project is open source and available under the [MIT License](LICENSE).

---

## 🙏 Acknowledgments

Built with ❤️ by the **Miraloma Elementary School** robotics community — students, parents, and teachers working together to bring robots to life.

- [PlatformIO](https://platformio.org/) — Embedded development platform
- [NiceGUI](https://nicegui.io/) — Python web UI framework
- [Google Gemini](https://ai.google.dev/) — AI powering the robot's brain
- [Keyestudio](https://www.keyestudio.com/) — Robot hardware kits
- [MakeCode](https://makecode.microbit.org/) — Micro:bit programming environment
- [Espressif](https://www.espressif.com/) — ESP32 microcontrollers & ESP-NOW protocol
