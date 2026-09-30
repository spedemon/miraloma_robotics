# Mira Builds and GitHub Releases

This document defines the canonical way to build and publish Mira. The desktop
application, both firmware roles, and the firmware manifest are distributed
together from one GitHub Release.

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

## Publish a release

Create and push one semantic-version tag:

```bash
git tag v0.2.0
git push origin v0.2.0
```

The **Build Mira Desktop** workflow builds firmware on Linux, packages the
macOS and Windows applications on GitHub-hosted runners, and publishes one
GitHub Release only after all three jobs succeed. A manual workflow run creates
downloadable workflow artifacts for testing but does not publish a release.

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
| `mira-robot-<firmware-version>-factory.bin` | Complete image for a blank robot board |
| `mira-wireless-controller-<firmware-version>.bin` | Update image for an existing wireless controller |
| `mira-wireless-controller-<firmware-version>-factory.bin` | Complete image for a blank controller board |
| `Mira-<app-version>-macOS-<arch>.dmg` | macOS application and launcher |
| `Mira-Setup-<app-version>.exe` | Windows installer and launcher |

Firmware versions come from `MIRA_FIRMWARE_VERSION` in each firmware project's
`include/config.h`. The application version comes from the `v<version>` Git tag.
The versions may advance independently.

`manifest.json` is the copy bundled inside the desktop application for offline
recovery. It is intentionally not a public release asset. The public manifest
has the unambiguous name `mira-firmware-manifest.json`.

## How Mira finds the latest firmware

Mira requests the repository's latest non-draft, non-prerelease GitHub Release,
finds `mira-firmware-manifest.json`, and locates every firmware binary by the
exact asset name recorded in that manifest. Each download is checked against
the manifest's SHA-256 digest before it can be flashed.

If GitHub cannot be reached, Mira falls back first to the firmware bundled in
the installed application and then to its last cached manifest. This means a
fresh installation can still provision boards offline, while an online
installation can discover newer firmware without downloading a new desktop app.

Do not replace release assets manually. Publish a new tag whenever firmware or
an installer changes so GitHub's “latest release” remains an immutable,
internally consistent set.
