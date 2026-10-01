# Mira Bluetooth Low Energy protocol

Robot firmware 0.6.0 introduces a direct BLE transport alongside USB serial
and ESP-NOW. A BLE controller owns direct control while connected; targeted
ESP-NOW motion commands receive `BUSY BLE_CONNECTED`. `stop` remains accepted
from either transport for safety. Disconnecting BLE immediately stops motion.

## GATT service

| Item | UUID | Access |
|---|---|---|
| Mira service | `7f510001-1b15-4f8e-9f5d-6f6d69726100` | advertised |
| Command | `7f510002-1b15-4f8e-9f5d-6f6d69726100` | write / write without response |
| Response | `7f510003-1b15-4f8e-9f5d-6f6d69726100` | read / notify |
| Device information | `7f510004-1b15-4f8e-9f5d-6f6d69726100` | read |

The advertised local name is `Mira-XXXX`, where `XXXX` is derived from the
robot's stable Wi-Fi MAC address. Device information is ASCII metadata:

```text
role=robot id=AA:BB:CC:DD:EE:FF firmware=0.6.0 protocol=2 hardware=esp32c3
```

Commands use the same UTF-8 text protocol as USB and are at most 240 bytes.
One complete command is sent per GATT write; a trailing CR/LF is optional.
Responses are newline framed and delivered through notifications. Clients must
reassemble notification fragments until `\n`; firmware uses 20-byte chunks so
it also works before a larger MTU has been negotiated.

Only one BLE central is supported at a time. The firmware advertises again
after disconnect. BLE and ESP-NOW share the ESP32-C3 radio using the Espressif
coexistence support; Wi-Fi remains in station mode on the ESP-NOW channel.
