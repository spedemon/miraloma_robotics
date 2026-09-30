# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

app_dir = Path(SPECPATH)
icon_name = "Mira.icns" if sys.platform == "darwin" else "Mira.ico"
icon_path = app_dir / "build" / icon_name
app_version = os.environ.get("MIRA_VERSION", "0.1.0")
esptool_datas, esptool_binaries, esptool_hiddenimports = collect_all("esptool")
firmware_dir = app_dir / "firmware"
app_datas = [(str(app_dir / "static"), "static"), *esptool_datas]
if firmware_dir.exists():
    app_datas.append((str(firmware_dir), "firmware"))

a = Analysis(
    [str(app_dir / "desktop_launcher.py")],
    pathex=[str(app_dir)],
    binaries=esptool_binaries,
    datas=app_datas,
    hiddenimports=["engineio.async_drivers.threading", *esptool_hiddenimports],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mira",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)

contents = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Mira",
)

if sys.platform == "darwin":
    app = BUNDLE(
        contents,
        name="Mira.app",
        icon=str(icon_path),
        bundle_identifier="org.miraloma.mira",
        info_plist={
            "CFBundleDisplayName": "Mira",
            "CFBundleName": "Mira",
            "CFBundleShortVersionString": app_version,
            "CFBundleVersion": app_version,
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Miraloma Robotics",
        },
    )
