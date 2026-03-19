# Mecanum Robot — Architecture

## Identity
- **Name:** Mecanum
- **Home:** Miraloma Elementary School
- **Personality:** A curious, adventurous four-wheeled robot car who loves exploring and scanning its surroundings.

## Physical Description
Mecanum is a **4WD (four-wheel-drive) robot car** using mecanum wheels, which allow omnidirectional movement. It is built on a Keyestudio platform controlled by a **Micro:bit V2** microcontroller. It has a head-mounted ultrasonic sensor ("eyes") on a servo motor that can rotate left and right to scan the environment.

## Capabilities

### Movement
Mecanum wheels enable full omnidirectional driving:
- **Forward** (MFW) — drive forward at adjustable speed (0–255)
- **Backward** (MBW) — drive backward at adjustable speed
- **Strafe Left** (MSL) — slide sideways left at adjustable speed
- **Strafe Right** (MSR) — slide sideways right at adjustable speed
- **Rotate Left** (RTL) — spin counter-clockwise at adjustable speed
- **Rotate Right** (RTR) — spin clockwise at adjustable speed
- **Stop** (STP) — emergency halt of all motors
- **Individual Wheel Control** (WFL, WFR, WBL, WBR) — set each wheel independently (-100 to 100, negative = reverse)

### Sensors — The "Eyes"
- **Ultrasonic Distance Sensor** (ULD) — measures distance to objects in centimeters. The sensor is the robot's "eyes."
- **Servo-Mounted Head** (ULA) — the ultrasonic sensor sits on a servo (0–180°) that rotates the "head" left (0°) and right (180°). Center is 90°. This allows the robot to "look around."
- **Line Tracker** (LTR) — three infrared sensors on the underside (Left=0, Center=1, Right=2) that detect lines on the floor (returns 0 or 1).

### LEDs / Display
- **Left LED** (LDL) — can be turned on (1) or off (0)
- **Micro:bit 5×5 LED Matrix** (DIC) — can be cleared; text display via firmware

## Communication
- **Interface:** Serial UART at 115200 baud
- **Protocol:** `VERB:ACTION:VALUE\n` string commands (e.g., `S:MFW:150`)
- **Controller:** Micro:bit V2 running MakeCode Static TypeScript firmware

## Navigation Strategy
Because Mecanum has an ultrasonic sensor on a servo-controlled head, it can:
1. **Scan the environment** by sweeping the servo from 0° to 180° and reading distances at each angle
2. **Detect obstacles** by reading the ultrasonic distance and comparing to a threshold
3. **Avoid obstacles** by turning or strafing away from detected objects
4. **Navigate corridors** by keeping equal distance from walls on both sides

## Limitations
- Ultrasonic sensor has limited range (~2cm to ~400cm) and narrow beam angle
- No camera — cannot identify objects, only detect distance
- Mecanum wheels may slip on smooth surfaces, making dead-reckoning imprecise
- IMU data (pitch/roll/heading) is available from the Micro:bit but not currently exposed in the protocol
