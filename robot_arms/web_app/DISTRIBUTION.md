# Mira Builds and GitHub Releases

This document defines the canonical way to build and publish Mira. The desktop
application, Android application, both firmware roles, and the firmware
manifest are distributed together from one GitHub Release.

## Build everything locally

Install Python 3.13 and PlatformIO, then run the coordinator from the repository
root:

```bash
python3 -m pip install platformio
python3 robot_arms/web_app/scripts/build_all.py --version 0.2.0
```

The command builds both ESP32-C3 firmware projects, creates their checksummed
manifest, and packages the desktop application for the computer it runs on.

- On macOS it produces `robot_arms/web_app/dist/Mira-<version>-macOS-<arch>.dmg`.
- On Windows it produces `robot_arms/web_app/dist/Mira-Setup-<version>.exe` and
  requires Inno Setup 6.
- Desktop installers are native builds. A Mac cannot create the Windows
  installer and Windows cannot create the macOS disk image.

Useful partial commands:

```bash
# Firmware binaries and manifests only (works on Linux, macOS, and Windows)
python3 robot_arms/web_app/scripts/build_all.py --firmware-only

# Native desktop package only, using the files already in firmware/
python3 robot_arms/web_app/scripts/build_all.py --app-only --version 0.2.0
```

The older `build_macos.sh` and `build_windows.ps1` files are platform-specific
implementation scripts called by `build_all.py`; the coordinator is the public
entry point.

Build the self-signed Android package separately with:

```bash
robot_arms/android_app/scripts/build_release.sh 0.2.0
```

The first build creates a private update key under the ignored
`robot_arms/android_app/keystore/` directory. Back it up securely and never
commit it. All later Android updates must use the same key. See the
[Android build guide](../android_app/README.md) for details.

## Publish a release

Create and push one semantic-version tag:

```bash
git tag v0.2.0
git push origin v0.2.0
```

The **Build Mira** workflow builds firmware on Linux, packages the macOS,
Windows, and signed Android applications on GitHub-hosted runners, and
publishes one GitHub Release only after every build succeeds. A manual workflow
run creates downloadable workflow artifacts for testing but does not publish a
release. If the four `MIRA_ANDROID_*` repository secrets documented in the
Android build guide are configured, the APK is built and attached
automatically. Otherwise that job is skipped and a locally signed APK must be
uploaded to the release.

Windows packaging is configured and exercised by the GitHub Windows runner,
but it has not yet been validated on a physical Windows computer. Treat the
Windows installer as experimental until that installation and device-update
flow has been tested end to end.

## Release asset contract

Every published release uses these names:

| Asset | Purpose |
|---|---|
| `mira-firmware-manifest.json` | Public firmware index read by Mira |
| `mira-robot-<firmware-version>.bin` | Update image for an existing robot |
| `mira-robot-<firmware-version>-factory.bin` | Complete image for setting up or repairing a robot board |
| `mira-wireless-controller-<firmware-version>.bin` | Update image for an existing wireless controller |
| `mira-wireless-controller-<firmware-version>-factory.bin` | Complete image for setting up or repairing a controller board |
| `Mira-<app-version>-macOS-<arch>.dmg` | macOS application and launcher |
| `Mira-Setup-<app-version>.exe` | Windows installer and launcher |
| `Mira-<app-version>-Android.apk` | Self-signed Android application |

Firmware versions come from `MIRA_FIRMWARE_VERSION` in each firmware project's
`include/config.h`. The application version comes from the `v<version>` Git tag.
The versions may advance independently.

Schema 2 manifests also contain the ELF SHA-256 fingerprint of each application
and a cumulative `known_images` history. Mira uses these fingerprints during
read-only flash inspection when a board cannot answer the normal serial
identity handshake. Do not remove older entries: they allow deployed boards to
be recognized as a Robot or Wireless board even when their application is not
starting. The manifest builder preserves this history automatically.

`manifest.json` is the copy bundled inside the desktop application for offline
recovery. It is intentionally not a public release asset. The public manifest
has the unambiguous name `mira-firmware-manifest.json`.

## How Mira finds the latest firmware

Mira requests the repository's latest non-draft, non-prerelease GitHub Release,
finds `mira-firmware-manifest.json`, and locates every firmware binary by the
exact asset name recorded in that manifest. Each download is checked against
the manifest's SHA-256 digest before it can be flashed.

Mira merges bundled, cached, and online manifests and keeps the newest firmware
for each role, so an older GitHub release cannot downgrade a newer bundled
image. If GitHub cannot be reached, the bundled and cached metadata remain
available. This means a fresh installation can still provision boards offline, while an online
installation can discover newer firmware without downloading a new desktop app.

Publish a new tag whenever firmware or an installer changes so GitHub's
“latest release” remains an immutable, internally consistent set. The Android
APK is produced with the protected long-lived update key and uploaded to the
same release.
