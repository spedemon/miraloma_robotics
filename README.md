# 🤖 Miraloma Robots

> **Talk to your robot, and watch it move!**
> A voice & chat-powered robotics platform built for kids at [Miraloma Elementary School](https://miralomasf.com/).

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![NiceGUI](https://img.shields.io/badge/NiceGUI-2.0+-4ECDC4)
![Gemini AI](https://img.shields.io/badge/Google%20Gemini-AI-A855F7?logo=google&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

![Miraloma Robots UI](static/screenshot.png)

---

## ✨ What Is This?

Miraloma Robots is an **AI-powered robot control center** that lets kids talk to their robots using plain English — by voice or text. The AI (Google Gemini) understands what they want to do, generates Python code in real-time, and sends commands to the robot over a serial (USB) connection.

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
# Clone the repo
git clone https://github.com/spedemon/miraloma_bots.git
cd miraloma_bots

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

### Mecanum Car
- **Platform:** Micro:bit V2 + Keyestudio Mecanum chassis
- **Movement:** Omnidirectional (forward, backward, strafe, rotate)
- **Sensors:** Ultrasonic distance (servo-mounted head), 3-channel line tracker
- **Firmware:** MakeCode Static TypeScript

### Spider Walker
- **Platform:** ESP8266 + ACB_Spider servo legs
- **Movement:** Walk in all directions, rotate
- **Special:** 9 preset animations (dance, pushup, greet, etc.)
- **Firmware:** Arduino/ACECode C

---

## 🧠 How the AI Works

1. You type or say a command (e.g., *"move forward 2 feet"*)
2. **Gemini** receives the command along with a system prompt that includes the robot's full command reference and architecture
3. The AI classifies the intent:
   - **`[ACTION]`** — simple command → generates Python code and **runs it immediately**
   - **`[NAVIGATION]`** — complex navigation → generates code and **waits for you to press Go!**
   - **Conversation** — no code, just a friendly chat reply
4. Generated code uses the `nav_runtime` API: `send()`, `read()`, `stop()`, `wait()`, `is_running()`
5. Code executes in a background thread; the **🛑 STOP** button (or voice "stop") kills it instantly

---

## 🤝 Contributing

We welcome contributions from parents, teachers, and fellow robotics enthusiasts!

### Adding a New Robot

1. Create a folder under `robots_firmware/<robot_name>/`
2. Add three files:
   - **`protocol.yaml`** — defines all UART commands (setters + getters). Use `mecanum/protocol.yaml` as a template.
   - **`robot_architecture.md`** — describes the robot's identity, capabilities, and limitations (this is fed to the AI as context).
   - **Firmware source** (`.ts`, `.c`, `.py`, etc.) — the code users flash onto the microcontroller.
3. The robot will auto-appear in the **Setup** tab dropdown!

### Development Workflow

```bash
# Fork the repo & clone your fork
git clone https://github.com/<your-username>/miraloma_bots.git
cd miraloma_bots

# Install dependencies
pip install -r requirements.txt

# Run the app (hot-reload is on by default unless using --native)
python main.py

# To run in a native app window:
python main.py --native
```

### Areas Where Help Is Needed

- **Testing** — End-to-end testing with actual robots, unit tests
- **New robots** — Add support for more robot platforms
- **UI improvements** — Responsive layout, mobile support
- **Firmware** — Improve or add safety features to robot firmware
- **Translations** — Make the UI accessible to non-English speakers

---

## 📜 License

This project is open source and available under the [MIT License](LICENSE).

---

## 🙏 Acknowledgments

Built with ❤️ by the Miraloma Elementary School robotics community.

- [NiceGUI](https://nicegui.io/) — Beautiful Python-based web UI framework
- [Google Gemini](https://ai.google.dev/) — AI powering the robot's brain
- [Keyestudio](https://www.keyestudio.com/) — Mecanum robot hardware
- [MakeCode](https://makecode.microbit.org/) — Micro:bit programming environment
