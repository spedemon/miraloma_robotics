# 🚗 Wheeled Bots

> Part of [Miraloma Robotics](../README.md)

> **Talk to your robot, and watch it move!**
> A voice & chat-powered robotics platform built for kids at [Miraloma Elementary School](https://miralomasf.com/).

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![NiceGUI](https://img.shields.io/badge/NiceGUI-2.0+-4ECDC4)
![Gemini AI](https://img.shields.io/badge/Google%20Gemini-AI-A855F7?logo=google&logoColor=white)

![Miraloma Robots UI](static/screenshot.png)

---

## ✨ What Is This?

Wheeled Bots is an **AI-powered robot control center** that lets kids talk to their robots using plain English — by voice or text. The AI (Google Gemini) understands what they want to do, generates Python code in real-time, and sends commands to the robot over a serial (USB) connection.

**Example commands:**
- *"Move forward 3 feet"* → robot drives forward for exactly 3 feet
- *"Explore the room and avoid obstacles"* → generates a navigation loop with sensor readings
- *"Do a dance!"* → triggers a fun robot animation

---

## 🎮 Features

| Feature                   | Description                                                         |
| ------------------------- | ------------------------------------------------------------------- |
| 🗣️ **Voice Chat**          | Talk to your robot using the microphone (Web Speech API)            |
| 💬 **Text Chat**           | Type commands in natural language                                   |
| 🧠 **AI Code Gen**         | Gemini generates & classifies Python code (action vs navigation)    |
| 🚀 **Auto-Execute**        | Simple commands run immediately; complex navigation waits for "Go!" |
| 🤖 **Multi-Robot**         | Switch between different robots (Mecanum car, Spider walker)        |
| 📟 **Firmware View**       | View and copy firmware source code for flashing                     |
| 📖 **Command Book**        | Auto-generated protocol reference from YAML definitions             |
| 🛑 **Emergency Stop**      | One-click stop button halts all motors instantly                    |
| 🎨 **Animated Robot Face** | SVG robot face that reacts to listening/thinking states             |
| ⚙️ **Calibration**         | Tune speed-per-foot and motor defaults per robot                    |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────┐
│               Browser (NiceGUI)                  │
│  ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │
│  │ Voice/   │ │ Animated │ │  Navigation     │  │
│  │ Text     │ │ Robot    │ │  Script Viewer  │  │
│  │ Chat     │ │ Face     │ │  + Go!/Stop     │  │
│  └────┬─────┘ └──────────┘ └────────┬────────┘  │
│       │                             │            │
├───────┴─────────────────────────────┴────────────┤
│               Python Backend                     │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐  │
│  │ Gemini     │ │ Navigation │ │ Robot HAL    │  │
│  │ Client     │ │ Runtime    │ │ (pyserial)   │  │
│  └──────┬─────┘ └─────┬──────┘ └──────┬───────┘  │
│         │             │               │          │
│    AI Response    exec(code)    UART commands    │
├───────────────────────────────────────┬──────────┤
│                                       │          │
│                              USB Serial          │
│                                       │          │
│                    ┌──────────────────┴───┐      │
│                    │  Micro:bit / ESP8266 │      │
│                    │  (Firmware Bridge)   │      │
│                    └──────────────────────┘      │
└──────────────────────────────────────────────────┘
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.10+**
- A **Google Gemini API key** — get one free at [Google AI Studio](https://aistudio.google.com/apikey)
- A supported robot with USB serial connection (Micro:bit or ESP8266-based)

### Installation

```bash
# Clone the monorepo
git clone https://github.com/spedemon/miraloma_robotics.git
cd miraloma_robotics/wheeled_bots

# Install Python dependencies
pip install -r requirements.txt

# Run the app
python main.py

# Optional: Run on a different port (default: 8080)
python main.py --port 8888

# Optional: Run in native window mode
python main.py --native
```

The app opens at **http://localhost:8080** (or your specified port).

### First-Time Setup

1. Go to the **⚙️ Setup** tab
2. **Pick your robot** (Mecanum or Spider)
3. **Connect** — select the USB port and click "Plug In!"
4. **Add your API key** — paste your Gemini API key and click "Save & Test"
5. Switch to the **🎮 Play** tab and start talking to your robot!

---

## 📂 Project Structure

```
wheeled_bots/
├── main.py                  # NiceGUI app — UI, handlers, launch
├── gemini_client.py         # Google Gemini API wrapper & response parser
├── robot_hal.py             # Hardware Abstraction Layer (serial/UART)
├── nav_runtime.py           # Runtime API for LLM-generated scripts
├── requirements.txt         # Python dependencies
├── static/
│   └── logo.png             # App logo
├── robots_firmware/
│   ├── mecanum/             # Mecanum car robot
│   │   ├── main.ts          # MakeCode firmware (Static TypeScript)
│   │   ├── protocol.yaml    # UART command definitions
│   │   └── robot_architecture.md   # Robot identity & capabilities
│   └── spider/              # Spider walker robot
│       ├── main.c           # ACECode/Arduino firmware
│       ├── protocol.yaml    # UART command definitions
│       └── robot_architecture.md   # Robot identity & capabilities
├── MASTER_PLAN.md           # Original technical specification
└── ROADMAP.md               # Project roadmap & progress
```

---

## 🤖 Supported Robots

Both robots share a **unified architecture**: custom firmware implements a **UART protocol** that gives direct access to actuators, sensors, and I/O over a USB serial connection. The Python **Navigation Runtime** wraps that UART interface in an object-oriented `Robot` class whose documentation is fed to the Gemini AI agent.

### Mecanum Car

|             |                                                                                     |
| ----------- | ----------------------------------------------------------------------------------- |
| **MCU**     | [BBC Micro:bit V2](https://microbit.org/) — ARM-based Nordic Semiconductor nRF52833 |
| **Chassis** | Keyestudio Mecanum 4WD — omnidirectional wheels                                     |
| **Sensors** | Ultrasonic distance (servo-mounted), 3-channel line tracker                         |
| **IDE**     | [Microsoft MakeCode for Micro:bit](https://makecode.microbit.org/) (web-based)      |

The Micro:bit V2 is programmed using **MakeCode Micro:bit**, a web-based tool with a **block programming** interface for kids. MakeCode compiles **Static TypeScript (STS)** to **ARM Thumb machine code** directly in the browser and uses **WebUSB** to flash the device.

**Firmware:** Custom STS script (`main.ts`) implementing a UART protocol. To flash:

1. Open the **Robot Code** tab in the app and copy the firmware source
2. Paste it into [MakeCode](https://makecode.microbit.org/) (switch to JavaScript/TypeScript view)
3. Click **Download** — MakeCode flashes the Micro:bit via WebUSB

---

### Spider Walker

|             |                                                                       |
| ----------- | --------------------------------------------------------------------- |
| **MCU**     | ESP8266 (Wi-Fi SoC)                                                   |
| **Chassis** | ACEBott Spider — multi-servo hexapod-style walker                     |
| **Library** | `ACB_Spider_ESP8266` (provided by ACEBott)                            |
| **IDE**     | [ACECode](https://www.acebott.com/) (desktop app for macOS / Windows) |

The Spider uses an **ESP8266** programmed via **ACECode**, which generates **C / Arduino** code and compiles and flashes it to the device.

**Firmware:** Custom C firmware (`main.c`) wrapping the **ACB_Spider_ESP8266** library. To flash:

1. Open the **Robot Code** tab in the app and copy the firmware source
2. Open ACECode, paste the C code in the code panel
3. Click **Upload** to compile and flash the ESP8266

---

### Unified Robot API

Both robots implement the same UART protocol structure. The Python `Robot` class in `nav_runtime.py` wraps these into a unified API, so AI-generated code like `robot.move_forward(150)` works identically on both platforms.

---

## 🧠 How the AI Works

1. You type or say a command (e.g., *"move forward 2 feet"*)
2. **Gemini** receives the command along with a system prompt that includes the robot's full command reference
3. The AI classifies the intent:
   - **`[ACTION]`** — simple command → generates Python code and **runs it immediately**
   - **`[NAVIGATION]`** — complex navigation → generates code and **waits for you to press Go!**
   - **Conversation** — no code, just a friendly chat reply
4. Generated code uses the `nav_runtime` API: `send()`, `read()`, `stop()`, `wait()`, `is_running()`
5. Code executes in a background thread; the **🛑 STOP** button (or voice "stop") kills it instantly

---

## 📡 Autonomous Navigation: Distance-to-Target System

This system provides high-precision distance measurement between two active nodes using a "Sync-and-Calculate" method with **ESP-NOW** and **HY-SRF05** ultrasonics.

### System Architecture

1. **Node A (Initiator)** sends an ESP-NOW radio packet and simultaneously triggers its ultrasonic pulse
2. **Node B (Responder)** receives the radio packet, starts a timer, and waits for the ultrasonic pulse
3. **Node B** calculates the distance and sends it back via radio

### Technical Specifications

| Feature                 | Specification                                       |
| :---------------------- | :-------------------------------------------------- |
| **Maximum Distance**    | **4.5 - 5.0 Meters** (Limited by sound attenuation) |
| **Minimum Distance**    | **2.0 Centimeters**                                 |
| **Expected Resolution** | **3 mm** (Dependent on clock timing)                |
| **Update Rate**         | **10Hz - 20Hz** (Configurable via UART)             |
| **Communication**       | **ESP-NOW** (2.4GHz Peer-to-Peer)                   |

---

## 🤝 Contributing

See the [monorepo contributing guide](../README.md#-contributing) for general guidelines.

### Adding a New Robot

1. Create a folder under `robots_firmware/<robot_name>/`
2. Add three files:
   - **`protocol.yaml`** — defines all UART commands. Use `mecanum/protocol.yaml` as a template.
   - **`robot_architecture.md`** — describes the robot's identity and capabilities (fed to the AI).
   - **Firmware source** (`.ts`, `.c`, `.py`, etc.) — the code users flash onto the microcontroller.
3. The robot will auto-appear in the **Setup** tab dropdown!

### Development Workflow

```bash
cd miraloma_robotics/wheeled_bots
pip install -r requirements.txt
python main.py
```

---

## 📜 License

This project is open source and available under the [MIT License](../LICENSE).

---

## 🙏 Acknowledgments

Built with ❤️ by the Miraloma Elementary School robotics community.

- [NiceGUI](https://nicegui.io/) — Beautiful Python-based web UI framework
- [Google Gemini](https://ai.google.dev/) — AI powering the robot's brain
- [Keyestudio](https://www.keyestudio.com/) — Mecanum robot hardware
- [MakeCode](https://makecode.microbit.org/) — Micro:bit programming environment
