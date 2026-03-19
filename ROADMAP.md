# 🗺️ Roadmap: Miraloma Bots — Miraloma Robots

> AI-powered voice & chat robot control — NiceGUI + Google Gemini + Serial UART

---

## ✅ Completed

### Phase 1 — Foundation & UI

| Deliverable                                                                     | Status |
| ------------------------------------------------------------------------------- | ------ |
| NiceGUI 4-tab app (Play, Robot Code, Command Book, Setup)                       | ✅      |
| Custom CSS design system (colors, gradients, animations, typography)            | ✅      |
| App header with animated robot logo, robot badge, connection badge, STOP button | ✅      |
| Status bar with version indicator                                               | ✅      |
| `requirements.txt` with all dependencies                                        | ✅      |
| `.gitignore` for Python/dev artifacts                                           | ✅      |
| `MASTER_PLAN.md` technical specification                                        | ✅      |
| `ROADMAP.md` (this file)                                                        | ✅      |
| Static assets served (`/static/logo.png`)                                       | ✅      |

### Phase 2 — Multi-Robot Support

| Deliverable                                                                                             | Status |
| ------------------------------------------------------------------------------------------------------- | ------ |
| YAML-based protocol definitions (`protocol.yaml` per robot)                                             | ✅      |
| Robot architecture markdown files (identity, capabilities, limitations)                                 | ✅      |
| Auto-discovery of robots from `robots_firmware/` subdirectories                                         | ✅      |
| Robot selector in Setup tab with dynamic UI updates                                                     | ✅      |
| **Mecanum Car** — Micro:bit V2, MakeCode STS firmware, omnidirectional, ultrasonic sensor, line tracker | ✅      |
| **Spider Walker** — ESP8266, ACECode/Arduino firmware, 9 preset actions/animations                      | ✅      |
| Platform-aware firmware tab (MakeCode vs Arduino IDE, copy/open buttons)                                | ✅      |
| Auto-generated Protocol Docs table from YAML                                                            | ✅      |
| Legacy `protocol_map.json` removed (replaced by per-robot YAML)                                         | ✅      |

### Phase 3 — Hardware Abstraction Layer

| Deliverable                                                                                       | Status |
| ------------------------------------------------------------------------------------------------- | ------ |
| `robot_hal.py` — thread-safe pyserial wrapper                                                     | ✅      |
| Dynamic protocol loading from YAML (setters/getters by ID)                                        | ✅      |
| Generic `send_command()` and `read_sensor()` with template substitution                           | ✅      |
| Emergency `stop()` with fallback                                                                  | ✅      |
| Serial port auto-detection (`list_ports`)                                                         | ✅      |
| Connect/disconnect lifecycle with UI status updates                                               | ✅      |
| Convenience methods: `drive()`, `set_servo()`, `read_distance()`, `display_text()`, `play_tone()` | ✅      |

### Phase 4 — Google Gemini AI Integration

| Deliverable                                                                                      | Status |
| ------------------------------------------------------------------------------------------------ | ------ |
| `gemini_client.py` — official `google-genai` SDK wrapper                                         | ✅      |
| Multi-turn chat with conversation history                                                        | ✅      |
| Model selector (Gemini 2.5 Flash, Pro, Flash-Lite)                                               | ✅      |
| API key configuration with "Save & Test" flow                                                    | ✅      |
| Dynamic system prompt with robot identity, architecture, protocol, and calibration               | ✅      |
| Response classification: `[ACTION]` (auto-execute), `[NAVIGATION]` (confirm first), conversation | ✅      |
| Code extraction from fenced code blocks                                                          | ✅      |
| Friendly error handling (invalid key, rate limits)                                               | ✅      |

### Phase 5 — Voice Chat & Animated UI

| Deliverable                                                    | Status |
| -------------------------------------------------------------- | ------ |
| Voice input via browser Web Speech API (Chrome/Edge)           | ✅      |
| Microphone toggle button with recording state animation        | ✅      |
| Animated SVG robot face (idle, listening, thinking states)     | ✅      |
| Eye blink, pupil tracking, antenna glow, sound wave animations | ✅      |
| Thinking dots and gear icon during AI processing               | ✅      |
| Face state transitions driven by voice/chat lifecycle          | ✅      |

### Phase 6 — Code Generation & Execution Engine

| Deliverable                                                               | Status |
| ------------------------------------------------------------------------- | ------ |
| `nav_runtime.py` — sandboxed API for LLM-generated scripts                | ✅      |
| Runtime functions: `send()`, `read()`, `stop()`, `wait()`, `is_running()` | ✅      |
| Interruptible `wait()` (checks `running` flag at 100ms intervals)         | ✅      |
| Background execution via `asyncio.to_thread(exec, ...)`                   | ✅      |
| Auto-execute for `[ACTION]` commands                                      | ✅      |
| "Go!" button for `[NAVIGATION]` confirmation flow                         | ✅      |
| "Start Over" button to clear script + stop execution                      | ✅      |
| Collapsible code viewer panel (auto-expands when code is generated)       | ✅      |
| Emergency stop kills running script + sends motor halt                    | ✅      |

### Phase 7 — Setup & Calibration

| Deliverable                                       | Status |
| ------------------------------------------------- | ------ |
| Speed calibration (seconds per foot)              | ✅      |
| Default motor speed calibration                   | ✅      |
| Calibration values injected into AI system prompt | ✅      |
| Baud rate selection (auto-set per robot protocol) | ✅      |
| Serial port refresh button                        | ✅      |
| Link to Google AI Studio for API key              | ✅      |

---

## 🔧 In Progress / Planned

### UI Polish

- [ ] Use different animated robot graphics in the Play section based on the selected robot (Mecanum face vs Spider face)
- [ ] Improve robot icon in header — remove gray background box and make it transparent
- [ ] Persistent settings (remember last port, API key, robot selection across sessions)

### Firmware Improvements

- [ ] Safety watchdog in firmware — all-stop if no serial command received for >1 second
- [ ] IMU data exposure (pitch/roll/heading) in Mecanum protocol
- [ ] Improve Spider firmware with sensor support

### AI & Navigation

- [ ] "Stop" / "Abort" / "Wait" voice keywords → immediate `robot.stop()`
- [ ] Multi-step mission sequencing
- [ ] Scan-the-room pattern (servo sweep + distance readings as a built-in capability)
- [ ] Obstacle avoidance templates
- [ ] Connection loss detection + auto-reconnect

### New Robots

- [ ] Add more robot platforms (additional Micro:bit kits, Arduino-based robots, etc.)
- [ ] Community-contributed robot definitions

---

## 🧪 Testing

Testing is a major area that has **not been started yet**. The following test efforts are needed:

### Unit Tests
- [ ] `robot_hal.py` — mock serial port, verify command formatting and protocol lookups
- [ ] `gemini_client.py` — mock API responses, verify response parsing and classification
- [ ] `nav_runtime.py` — test `send()`, `read()`, `stop()`, `wait()`, `is_running()` with mock HAL
- [ ] Protocol YAML loading — verify all robot configs parse correctly

### Integration Tests
- [ ] Full chat → code generation → execution pipeline with mocked Gemini + serial
- [ ] Robot switching — verify all UI elements update (firmware, protocol table, system prompt)
- [ ] Emergency stop — verify script termination and motor halt at every stage

### End-to-End Tests (Manual)
- [ ] Connect a real Mecanum robot and test voice commands
- [ ] Connect a real Spider robot and test preset actions
- [ ] Test voice input in Chrome and Edge browsers
- [ ] Test with all three Gemini model options
- [ ] Verify calibration changes affect generated code timing

### Browser / UI Tests
- [ ] Verify all tabs render correctly
- [ ] Test voice input toggle (start/stop recording)
- [ ] Test robot face state transitions (idle → listening → thinking → idle)
- [ ] Test collapsible code panel (expand/collapse, auto-expand on code gen)
- [ ] Test "Go!" and "Start Over" buttons

---

## 📝 Notes

- The original `protocol_map.json` has been replaced by per-robot `protocol.yaml` files
- The Micro:bit firmware (`main.ts`) is already written and ready to flash via MakeCode
- The Spider firmware (`main.c`) is ready to flash via Arduino IDE with the ACB_Spider_ESP8266 library
- The system prompt dynamically adapts to whichever robot is selected, including its full command reference and physical capabilities
