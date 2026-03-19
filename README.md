# miraloma_robotics

This project ("The Robot Mind") is a voice-integrated robotics control system. 

It leverages a **Micro:bit V2** as a "Hardware Bridge" and a **Host Computer (Python/NiceGUI)** as the primary intelligence and navigation engine.

## Overview

The system features:
- **Peripheral Bridge (STS Firmware):** A Thin Wrapper for Micro:bit controlling motors, sensors, and peripherals over UART.
- **Host Application (NiceGUI):** A Python-based dashboard for Gemini Multimodal Live API, script generation, and real-time navigation control.
- **AI Execution Engine:** Uses Gemini to translate voice/text intent into hardware-compatible Python code (using the `Robot` HAL).

## Project Structure

- `main.py`: NiceGUI entry point and UI.
- `gemini_client.py`: Gemini Multimodal Live API wrapper.
- `robot_hal.py`: Python Hardware Abstraction Layer for UART communication.
- `protocol_map.json`: Source of truth for commands.
- `MASTER_PLAN.md`: Technical specification and roadmap.
- `ROADMAP.md`: Project progression and milestones.

## Getting Started

1. Install requirements: `pip install -r requirements.txt`
2. Configure your Serial port and API Key in the UI.
3. Flash the STS firmware (to be generated) to your Micro:bit.
4. Run the host app: `python main.py`
