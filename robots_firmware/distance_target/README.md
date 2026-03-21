# 📡 Distance-to-Target System — Hardware Guide

> Centimeter-level distance measurement between a robot and a target beacon
> using ESP-NOW radio sync + HY-SRF05 ultrasonic time-of-flight.

---

## 📦 Bill of Materials (per system — 2 nodes)

| # | Component | Qty | Est. Cost | Notes |
|---|-----------|-----|-----------|-------|
| 1 | ESP32 DevKit V1 (or NodeMCU ESP8266) | 2 | ~$4 each | Any ESP32/ESP8266 with ESP-NOW support |
| 2 | HY-SRF05 Ultrasonic Sensor | 2 | ~$1.50 each | 5-pin version (Vcc, Trig, Echo, Out, GND) |
| 3 | 1 kΩ Resistor | 2 | — | For voltage divider |
| 4 | 2 kΩ Resistor | 2 | — | For voltage divider |
| 5 | Breadboard (half-size) | 2 | — | For prototyping |
| 6 | Jumper wires | ~10 | — | Male-to-male |
| 7 | Micro-USB cables | 2 | — | Power + serial |

**Total estimated cost: ~$12–15**

---

## 🔌 Wiring

### Node A (Initiator) — Mounts on Robot

```
ESP32 DevKit          HY-SRF05
┌──────────┐          ┌──────────┐
│          │          │          │
│   GPIO 5 ├──────────┤ Trig     │
│          │          │          │
│  GPIO 18 ├──┐       │ Echo     │
│          │  │       │          │
│      3V3 │  │  ┌────┤ Vcc      │  ← connect to 5V (USB VBUS or Vin)
│          │  │  │    │          │
│      GND ├──┼──┼────┤ GND      │
│          │  │  │    │          │
└──────────┘  │  │    │ Out      │  ← not connected
              │  │    └──────────┘
              │  │
              │  └── 5V supply (USB Vin pin)
              │
              └── Voltage Divider (see below)
```

### Node B (Responder) — Target Beacon

```
ESP32 DevKit          HY-SRF05
┌──────────┐          ┌──────────┐
│          │          │          │
│          │          │ Trig     │  ← not connected (Responder doesn't trigger)
│          │          │          │
│  GPIO 18 ├──┐       │ Echo     │
│          │  │       │          │
│      3V3 │  │  ┌────┤ Vcc      │  ← connect to 5V
│          │  │  │    │          │
│      GND ├──┼──┼────┤ GND      │
│          │  │  │    │          │
└──────────┘  │  │    │ Out      │  ← not connected
              │  │    └──────────┘
              │  │
              │  └── 5V supply
              │
              └── Voltage Divider (see below)
```

### ⚡ Voltage Divider (REQUIRED on Echo Pin)

The HY-SRF05 Echo pin outputs **5V** but the ESP32 GPIO is **3.3V tolerant only**.
Use a simple resistor divider to step the voltage down:

```
HY-SRF05 Echo ──── [ 1 kΩ ] ──┬── ESP32 GPIO 18
                               │
                          [ 2 kΩ ]
                               │
                              GND
```

**Output voltage:** 5V × 2kΩ / (1kΩ + 2kΩ) = **3.33V** ✓

> ⚠️ **Do NOT connect the Echo pin directly to the ESP32 without the divider —
> this will damage the ESP32's GPIO!**

---

## ⚡ Flash Instructions

### Prerequisites
1. Install the [Arduino IDE](https://www.arduino.cc/en/software) (2.x recommended)
2. Add ESP32 board support:
   - Go to **File → Preferences**
   - Add this URL to **Additional Board Manager URLs:**
     ```
     https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
     ```
   - Go to **Tools → Board → Board Manager**, search for "ESP32", and install

### Flash the Initiator (Node A)
1. Open `initiator.c` in Arduino IDE
2. **Important:** Edit the `responderMAC[]` array with the actual MAC address of your Responder (printed on the Responder's serial monitor at boot)
3. Select your board: **Tools → Board → ESP32 Dev Module**
4. Select the USB port: **Tools → Port**
5. Click **Upload**

### Flash the Responder (Node B)
1. Open `responder.c` in Arduino IDE
2. Select your board and port (same as above)
3. Click **Upload**
4. Note the **MAC address** printed on the serial monitor — you'll need it for the Initiator

### First Boot
1. Power on both nodes via USB
2. Open serial monitors on both (115200 baud)
3. Copy the Responder's MAC address into `initiator.c` and re-flash the Initiator
4. On the Initiator's serial monitor, type `EN` and press Enter
5. You should see `DIST: <value> cm` readings appearing at 10 Hz

---

## 💬 UART Commands

| Command | Description |
|---------|-------------|
| `EN` | Enable active measurement |
| `DIS` | Disable measurement |
| `GET` | Get the last measured distance |
| `RATE:<hz>` | Set update rate, e.g. `RATE:20` (Initiator only) |

### Output Format
```
DIST: 124.5 cm        ← Distance reading
STATUS: ENABLED        ← State change confirmation
STATUS: DISABLED       ← State change confirmation
DIST: -- cm            ← No reading available
DIST: -- cm (timeout)  ← Sound didn't arrive in time (out of range)
```

---

## 🔧 Troubleshooting

| Problem | Solution |
|---------|----------|
| No readings at all | Check wiring, ensure both nodes are powered, verify MAC address is correct |
| `DIST: -- cm (timeout)` | Nodes too far apart (>5 m), or no line of sight between sensors |
| Erratic readings | Check voltage divider, ensure sensors face each other, avoid reflective surfaces |
| `ERROR: ESP-NOW init failed` | Ensure WiFi.mode(WIFI_STA) is set, try power cycling the board |
| Wrong distance values | Verify temperature (~20°C assumed); formula uses 0.0343 cm/µs |
