#!/bin/bash
# flash.sh — Build, flash, and open serial monitor for Mira Master MCU
#
# Usage:
#   ./flash.sh              # Auto-detect USB port
#   ./flash.sh /dev/cu.X    # Use a specific port
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "  Mira Master MCU — Flash"
echo "========================================="
echo

# --- Port detection ---
if [ -n "$1" ]; then
    PORT="$1"
    echo "Using specified port: $PORT"
else
    # Look for ESP32-C3 USB port (typically usbmodem or usbserial)
    PORT=$(ls /dev/cu.usbmodem* /dev/cu.usbserial* /dev/cu.wchusbserial* 2>/dev/null | head -n1)

    if [ -z "$PORT" ]; then
        echo "❌ No USB serial port detected."
        echo ""
        echo "Available ports:"
        ls /dev/cu.* 2>/dev/null || echo "  (none)"
        echo ""
        echo "Make sure the ESP32-C3 is connected via USB."
        echo "You can also specify a port manually:"
        echo "  ./flash.sh /dev/cu.your_port"
        exit 1
    fi

    echo "Auto-detected port: $PORT"
fi

echo

# --- Upload ---
pio run -t upload --upload-port "$PORT"

echo
echo "✅ Flash complete"
echo
echo "To open the serial monitor, run:"
echo "  pio device monitor --port $PORT --baud 115200"
