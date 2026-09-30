#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$APP_DIR/.venv-desktop"
DIST_DIR="$APP_DIR/dist"
DMG_ROOT="$APP_DIR/build/dmg-root"
ARCH="$(uname -m)"
VERSION="${MIRA_VERSION:-0.1.0}"

cd "$APP_DIR"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements-desktop.txt
"$VENV_DIR/bin/python" scripts/create_icon.py static/logo.png build/Mira.icns
"$VENV_DIR/bin/pyinstaller" --noconfirm --clean Mira.spec

# PyInstaller applies an ad-hoc signature when no trusted identity is supplied.
# Re-sign the completed bundle to cover every nested component consistently.
codesign --force --deep --sign - "$DIST_DIR/Mira.app"
codesign --verify --deep --strict --verbose=2 "$DIST_DIR/Mira.app"

if [[ -e "$DMG_ROOT" ]]; then
    rm -rf "$DMG_ROOT"
fi
mkdir -p "$DMG_ROOT"
cp -R "$DIST_DIR/Mira.app" "$DMG_ROOT/Mira.app"
ln -s /Applications "$DMG_ROOT/Applications"

DMG_PATH="$DIST_DIR/Mira-$VERSION-macOS-$ARCH.dmg"
hdiutil create \
    -volname "Mira" \
    -srcfolder "$DMG_ROOT" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

echo "Built $DMG_PATH"
