$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $AppDir ".venv-desktop"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$PyInstaller = Join-Path $VenvDir "Scripts\pyinstaller.exe"

Set-Location $AppDir

if (-not (Test-Path $Python)) {
    py -3 -m venv $VenvDir
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements-desktop.txt
& $Python scripts/create_icon.py static/logo.png build/Mira.ico
& $PyInstaller --noconfirm --clean Mira.spec

$IsccCommand = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
if ($IsccCommand) {
    $IsccPath = $IsccCommand.Source
} else {
    $CommonPath = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $CommonPath) {
        $IsccPath = $CommonPath
    } else {
        throw "Inno Setup 6 is required to create the Windows installer."
    }
}

if (-not $env:MIRA_VERSION) {
    $env:MIRA_VERSION = "0.1.0"
}

& $IsccPath "installer\windows\Mira.iss"
Write-Host "Built dist\Mira-Setup-$($env:MIRA_VERSION).exe"
