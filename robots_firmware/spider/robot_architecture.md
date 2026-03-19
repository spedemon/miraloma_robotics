# Spider Robot — Architecture

## Identity
- **Name:** Spider
- **Home:** Miraloma Elementary School
- **Personality:** A friendly, playful four-legged spider robot who loves to dance and show off tricks.

## Physical Description
Spider is a **four-legged walking robot** built around an ESP8266 microcontroller and the ACB_Spider_ESP8266 library. Each leg has multiple servo-driven joints, giving Spider an expressive, insect-like walking gait.

## Capabilities

### Movement
Spider can walk in all four directions and rotate:
- **Forward** — walks forward using coordinated leg gaits
- **Backward** — walks backward
- **Strafe Left** — side-steps to the left
- **Strafe Right** — side-steps to the right
- **Rotate Left** — turns counter-clockwise in place
- **Rotate Right** — turns clockwise in place
- **Stop** — immediately halts all leg movement

### Pre-set Actions (Animations)
Spider has 9 built-in action routines:
1. **Standby** (ACT:1) — default standing pose
2. **Lying** (ACT:2) — lies down flat
3. **Sleep** (ACT:3) — sleepy resting pose
4. **Greet** (ACT:4) — waves a leg to say hello
5. **Pushup** (ACT:5) — does pushups
6. **Fighting** (ACT:6) — aggressive fighting stance
7. **Dancing** (ACT:7) — dances around
8. **Swing** (ACT:8) — swings side to side
9. **Handsome** (ACT:9) — strikes a cool pose

### Sensors
Spider currently has **no sensors** (no distance, no line tracking). It is a purely actuator-driven robot. Navigation must be time-based.

### LEDs / Display
Spider has **no LED display or matrix**. Feedback is purely through physical movement.

## Communication
- **Interface:** Serial UART at 115200 baud
- **Protocol:** `VERB:ACTION:VALUE\n` string commands
- **Controller:** ESP8266 running Arduino/ACECode firmware

## Limitations
- No obstacle detection — cannot sense objects in its path
- Walking speed is fixed (not adjustable via protocol)
- Movement commands have no speed parameter — just direction
- Must rely on time-based estimation for distances
