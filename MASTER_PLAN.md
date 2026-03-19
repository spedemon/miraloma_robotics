## 📑 Master Plan: "The Robot Mind" (Unified Host-Peripheral Architecture)

This document serves as the **Technical Specification and Execution Roadmap** for an AI coding agent to build a voice-integrated robotics control system. The system leverages a **Micro:bit V2** as a "Hardware Bridge" and a **Host Computer (Python/NiceGUI)** as the primary intelligence and navigation engine.

---

### 1. System Philosophy
The project treats the Micro:bit as a **Transparent Peripheral Controller**. 
- **The Micro:bit (MCU):** Runs a static firmware written in Static TypeScript (STS) that exposes I2C (motors), Pins (sensors), and Internal Peripherals (LED matrix, IMU) via a standardized UART string protocol.
- **The Host (PC):** Runs a **NiceGUI** application that handles the Gemini Multimodal Live API (Voice), Python code generation, and real-time execution of navigation logic.

---

### 2. Component A: The Peripheral Bridge (STS Firmware)
The coding agent must generate a `main.ts` file for MakeCode Micro:bit that acts as a "Thin Wrapper."

**Requirements:**
- **UART Protocol:** Listen at `115200 Baud`.
- **Command Format:** `CMD:VAL1:VAL2\n`.
- **Capabilities to Wrap:**
    - `M:L1:L2:R1:R2` -> Drive 4 Mecanum motors (via Keyestudio Extension).
    - `S:ANGLE` -> Set ultrasonic servo position.
    - `D:?` -> Return ultrasonic distance over Serial.
    - `I:?` -> Return Pitch/Roll/Heading from Micro:bit IMU.
    - `L:TEXT` -> Scroll text on the 5x5 LED matrix.
    - `B:TONE` -> Play a specific frequency.
- **Safety Watchdog:** If no Serial command is received for $>1000ms$, the firmware must call `mecanumRobotV2.state()` (All Stop).

---

### 3. Component B: The Host Application (NiceGUI)
The UI serves as the Mission Control for the robot.

**Core UI Layout:**
- **Tab 1: Workspace:** A chat interface for the Voice/Text system. Includes a "Live Visualizer" for the current Python navigation script being executed.
- **Tab 2: Firmware (STS):** A read-only code editor showing the generated STS code. Includes a **"Copy to Clipboard"** button for easy flashing to the Micro:bit.
- **Tab 3: Protocol Docs:** A dynamically generated Markdown table listing every UART command (e.g., `FW:100` -> "Move Forward at Speed 100").
- **Tab 4: Settings:** Serial Port selection (COM/tty) and API Key entry for Gemini.

---

### 4. Component C: The AI "Mind" & Execution Engine
This is the heart of the application, utilizing the **Gemini Multimodal Live API**.

**Logic Flow:**
1.  **Intent Classification:** - **Simple Commands:** (e.g., "Move 1m"). AI generates a short Python snippet and executes it **immediately**.
    - **Complex Navigation:** (e.g., "Scan area and find a path"). AI generates a robust Python script (using a `Robot` HAL class).
2.  **User Confirmation:** For complex scripts, the UI displays the code and the Voice says: *"Control system updated. Do you want to start?"*
3.  **Execution:** Upon "Yes," the script runs in a separate thread/process.
4.  **Stop Logic:** The system must listen for "Stop," "Abort," or "Wait" at all times. This triggers an immediate `robot.stop()` and kills the running Python navigation thread.

---

### 5. Technical Instructions for the Coding Agent

#### File Structure
- `main.py`: The NiceGUI entry point and UI layout.
- `gemini_client.py`: Wrapper for the Multimodal Live API and Function Calling.
- `robot_hal.py`: The Python Hardware Abstraction Layer that converts method calls (e.g., `drive()`) into UART strings.
- `navigation_temp.py`: A volatile file where the AI-generated navigation code is written and executed from.
- `protocol_map.json`: The "Source of Truth" defining the mapping between Python methods, UART strings, and STS logic.

#### Implementation Notes for the Agent:
- **WebSerial/PySerial:** Use `pyserial` for the backend. Ensure the serial port is shared thread-safely between the UI and the generated navigation scripts.
- **Code Generation Prompting:** The agent must pre-load Gemini with a "System Instruction" that includes the `robot_hal.py` signatures. This ensures the generated code is syntactically correct and hardware-compatible.
- **Asynchronous Execution:** Use Python `asyncio` to ensure the UI remains responsive while the robot is navigating or the AI is "thinking."

---

### 6. The "Safety First" Protocol
The coding agent must implement a **Force-Kill** button in the UI and a reserved "Stop" keyword in the voice system that sends a `0,0,0,0` motor command to the UART port with the highest priority, bypassing any currently running script queues.

---

### 7. Success Criteria
1.  User can copy the STS code, flash the Micro:bit, and connect via the NiceGUI UI.
2.  User can say "Scan the room," see the Python code appear in the UI, and trigger execution via voice confirmation.
3.  The robot stops immediately upon the voice command "Stop."

**Would you like me to generate the initial `protocol_map.json` to define the baseline commands for the AI coding agent?**