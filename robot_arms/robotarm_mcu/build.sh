#!/bin/bash
# build.sh — Build Mira Robot Arm MCU firmware
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "  Mira Robot Arm MCU — Build"
echo "========================================="
echo

pio run

echo
echo "✅ Build complete"
