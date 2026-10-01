#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-0.2.1}"
IFS=. read -r VERSION_MAJOR VERSION_MINOR VERSION_PATCH <<< "$VERSION"
VERSION_CODE=$((10#$VERSION_MAJOR * 10000 + 10#$VERSION_MINOR * 100 + 10#$VERSION_PATCH))

KEYSTORE_DIR="$APP_DIR/keystore"
KEYSTORE_FILE="${MIRA_ANDROID_KEYSTORE:-$KEYSTORE_DIR/mira-release.jks}"
SIGNING_FILE="$KEYSTORE_DIR/signing.env"

if [[ -f "$SIGNING_FILE" ]]; then
    # The generated file contains shell-safe URL alphabet values only.
    source "$SIGNING_FILE"
fi

if [[ ! -f "$KEYSTORE_FILE" ]]; then
    mkdir -p "$KEYSTORE_DIR"
    if [[ -n "${CI:-}" ]]; then
        echo "Android release keystore is missing. Configure the MIRA_ANDROID_KEYSTORE secret." >&2
        exit 1
    fi
    PASSWORD="$(openssl rand -base64 36 | tr -d '/+=' | head -c 40)"
    MIRA_ANDROID_KEYSTORE_PASSWORD="$PASSWORD"
    MIRA_ANDROID_KEY_PASSWORD="$PASSWORD"
    MIRA_ANDROID_KEY_ALIAS="mira"
    export MIRA_ANDROID_KEYSTORE_PASSWORD MIRA_ANDROID_KEY_PASSWORD MIRA_ANDROID_KEY_ALIAS
    keytool -genkeypair -noprompt \
        -keystore "$KEYSTORE_FILE" \
        -storepass "$MIRA_ANDROID_KEYSTORE_PASSWORD" \
        -keypass "$MIRA_ANDROID_KEY_PASSWORD" \
        -alias "$MIRA_ANDROID_KEY_ALIAS" \
        -keyalg RSA -keysize 4096 -validity 10950 \
        -dname "CN=Miraloma Robotics, OU=Robotics, O=Miraloma, L=San Francisco, ST=California, C=US"
    umask 077
    {
        echo "MIRA_ANDROID_KEYSTORE_PASSWORD=$MIRA_ANDROID_KEYSTORE_PASSWORD"
        echo "MIRA_ANDROID_KEY_PASSWORD=$MIRA_ANDROID_KEY_PASSWORD"
        echo "MIRA_ANDROID_KEY_ALIAS=$MIRA_ANDROID_KEY_ALIAS"
    } > "$SIGNING_FILE"
    echo "Created the private Android update key in $KEYSTORE_DIR"
    echo "Back up that directory securely; future APK updates must use the same key."
fi

: "${MIRA_ANDROID_KEYSTORE_PASSWORD:?Android keystore password is required}"
: "${MIRA_ANDROID_KEY_PASSWORD:?Android key password is required}"
: "${MIRA_ANDROID_KEY_ALIAS:=mira}"

export MIRA_ANDROID_KEYSTORE="$KEYSTORE_FILE"
export MIRA_ANDROID_KEYSTORE_PASSWORD MIRA_ANDROID_KEY_PASSWORD MIRA_ANDROID_KEY_ALIAS
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"

cd "$APP_DIR"
./gradlew clean assembleRelease \
    -PmiraVersion="$VERSION" \
    -PmiraVersionCode="$VERSION_CODE"

mkdir -p "$APP_DIR/dist"
OUTPUT="$APP_DIR/dist/Mira-$VERSION-Android.apk"
cp "$APP_DIR/app/build/outputs/apk/release/app-release.apk" "$OUTPUT"

APKSIGNER="$ANDROID_HOME/build-tools/35.0.0/apksigner"
if [[ ! -x "$APKSIGNER" ]]; then
    APKSIGNER="$(find "$ANDROID_HOME/build-tools" -type f -name apksigner | sort -V | tail -1)"
fi
"$APKSIGNER" verify --verbose "$OUTPUT"
echo "$OUTPUT"
