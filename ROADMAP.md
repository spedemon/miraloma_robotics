# 🗺️ Roadmap: "The Robot Mind"

> Voice-integrated robotics control system — Micro:bit V2 + Python/NiceGUI + Gemini AI

---

## Phase 1 — Foundation (v1) ✅ _Current_

**Goal:** Working NiceGUI app with serial connectivity and stubbed AI.

| Deliverable | Status |
|---|---|
| `ROADMAP.md` — this file | ✅ |
| `protocol_map.json` — UART command source of truth | ✅ |
| `requirements.txt` — Python dependencies | ✅ |
| `robot_hal.py` — Hardware Abstraction Layer (pyserial) | ✅ |
| `gemini_client.py` — AI client stub | ✅ |
| `main.py` — NiceGUI 4-tab UI | ✅ |

---

## Phase 2 — Peripheral Bridge (Micro:bit Firmware)

**Goal:** Flash a working STS firmware onto the Micro:bit V2.

- [ ] Generate `main.ts` (MakeCode Static TypeScript)
- [ ] Implement UART command parser (`CMD:VAL1:VAL2\n`)
- [ ] Wire motor control via Keyestudio extension (`M:L1:L2:R1:R2`)
- [ ] Servo, distance, IMU, LED, buzzer handlers
- [ ] Safety watchdog — all-stop if no command for >1 s
- [ ] End-to-end serial loopback test (Host ↔ Micro:bit)

---

## Phase 3 — Gemini Integration (Voice + Code Gen)

**Goal:** Connect the Gemini Multimodal Live API for voice commands and Python code generation.

- [ ] Implement `GeminiClient` with Multimodal Live API streaming
- [ ] Design system prompt embedding `robot_hal.py` signatures
- [ ] Intent classification: simple commands → instant exec, complex nav → confirmation flow
- [ ] Voice input/output via browser WebRTC or device mic
- [ ] Code generation → display in Workspace → user confirmation → execution
- [ ] "Stop" / "Abort" / "Wait" voice keywords → immediate `robot.stop()`

---

## Phase 4 — Navigation & Autonomy

**Goal:** Generated Python scripts that actually drive the robot.

- [ ] `navigation_temp.py` execution engine (sandboxed thread)
- [ ] Scan-the-room pattern (servo sweep + distance readings)
- [ ] Obstacle avoidance loop
- [ ] IMU-based dead-reckoning for distance commands
- [ ] Multi-step mission sequencing

---

## Phase 5 — Polish & Safety

**Goal:** Production-quality UX and robust safety.

- [ ] Force-Kill button hardened (bypasses all queues)
- [ ] Connection loss detection + auto-reconnect
- [ ] Persistent settings (last port, API key)
- [ ] Mobile-friendly responsive layout
- [ ] Logging / telemetry dashboard
- [ ] End-to-end integration tests
