# Mira for Android

[![Download the latest Android APK](https://img.shields.io/badge/Android-Download_latest_APK-3DDC84?logo=android&logoColor=white)](https://github.com/spedemon/miraloma_robotics/releases/latest)

Mira for Android is a small native WebView shell around the same HTML, CSS,
and JavaScript interface used by the desktop applications. The native layer
implements Bluetooth Low Energy discovery and communication; Gradle copies the
shared web interface from `../web_app/static` into the APK during every build.
There is therefore only one interface to maintain.

## Requirements

- Android Studio or Android SDK command-line tools
- Android SDK 35 and build tools 35
- Java 17
- Android 8.0 (API 26) or newer on the tablet

## Development build

```bash
cd robot_arms/android_app
./gradlew assembleDebug
```

The APK is written to `app/build/outputs/apk/debug/app-debug.apk`. Install it
with Android Studio, or with `adb install -r` while USB debugging is enabled.

## Signed release build

```bash
cd robot_arms/android_app
./scripts/build_release.sh 0.3.0
```

On the first run, the script creates a self-signed 4096-bit RSA update key in
the ignored `keystore/` directory and writes the APK to
`dist/Mira-<version>-Android.apk`. Back up the whole `keystore/` directory in a
secure password manager or encrypted backup. Android accepts future updates
only when they are signed by the same key. Losing it means existing users must
uninstall the app before installing a differently signed build.

The key is self-signed, so no Google Play or Apple developer account is needed.
Families install the APK from GitHub Releases after allowing their browser to
install apps from that source. Android will show its normal sideloading safety
warning.

For an automated build, provide these environment variables and the existing
keystore file:

- `MIRA_ANDROID_KEYSTORE`
- `MIRA_ANDROID_KEYSTORE_PASSWORD`
- `MIRA_ANDROID_KEY_PASSWORD`
- `MIRA_ANDROID_KEY_ALIAS`

Never commit the keystore or its passwords.

The Android package contains the shared HTML, CSS, and JavaScript plus its
native Java Bluetooth implementation. It does not embed Python or depend on a
separate runtime on the tablet. Gradle compiles the native code, copies the
current shared interface, and `apksigner` verifies the finished release APK;
any missing Android build dependency therefore stops the release build.

The GitHub workflow expects equivalent repository Actions secrets:

- `MIRA_ANDROID_KEYSTORE_BASE64`: base64 encoding of `mira-release.jks`
- `MIRA_ANDROID_KEYSTORE_PASSWORD`
- `MIRA_ANDROID_KEY_PASSWORD`
- `MIRA_ANDROID_KEY_ALIAS`

## Architecture

- `MainActivity` hosts the local WebView and requests the Android Bluetooth
  permissions.
- `MiraBleManager` scans for the Mira service, maintains multiple GATT
  connections, and sends newline-oriented commands.
- `MiraWebBridge` exposes the small native API expected by the shared UI.
- `web_app/static/mobile_bridge.js` presents a Socket.IO-like interface so the
  existing UI does not need an Android-specific fork.

The Android wrapper intentionally supports direct BLE connections only. USB
and the USB-to-ESP-NOW controller remain desktop options.
