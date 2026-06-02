#!/bin/bash
# build.sh — Build Mira Master MCU firmware
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "  Mira Master MCU — Build"
echo "========================================="
echo

pio run

echo
echo "✅ Build complete"
