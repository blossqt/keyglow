# Sets up everything Keyglow's build needs, in %LOCALAPPDATA%\KeyglowBuild so the project stays small.
# Safe to run again: each part is skipped once it is there.
#
#   powershell -ExecutionPolicy Bypass -File build\bootstrap.ps1
#
#   venv\        Python 3.12 with PySide6-Essentials and PyInstaller (requirements.txt)
#   msys64\      MSYS2 (UCRT64) with git, make, the ARM compiler and the QMK CLI, for the firmware
#   bin\qmk      the QMK CLI, let run from UCRT64 (the packaged one refuses any MSYS2 but MINGW64,
#                whose packages MSYS2 no longer carries)
#   qmk\         QMK 0.26.11: the last release with the Drop ALT v1 (its arm_atsam platform went in 0.27)
#   mdloader\    Drop's flashing tool, built from Massdrop/mdloader at a fixed commit

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root  = Split-Path -Parent $PSScriptRoot
$Cache = Join-Path $env:LOCALAPPDATA 'KeyglowBuild'
$Msys  = Join-Path $Cache 'msys64'
$Bash  = Join-Path $Msys 'usr\bin\bash.exe'
$QmkTag = '0.26.11'
$MdloaderCommit = 'c4d56b478da8a061231d1992a263a8a1ae5873c6'
New-Item -ItemType Directory -Force $Cache | Out-Null

function Unix($path) { '/' + $path.Substring(0, 1).ToLower() + ($path.Substring(2) -replace '\\', '/') }

# --- Python ---------------------------------------------------------------------------------
$Py = Join-Path $Cache 'venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
    Write-Host '>> venv'
    & py -3.12 -m venv (Join-Path $Cache 'venv')
}
& $Py -m pip install -q -r (Join-Path $PSScriptRoot 'requirements.txt')

# --- MSYS2 and the toolchain ------------------------------------------------------------------
if (-not (Test-Path $Bash)) {
    Write-Host '>> MSYS2'
    $Sfx = Join-Path $env:LOCALAPPDATA 'GrabbitBuild\downloads\msys2-base-x86_64-latest.sfx.exe'
    if (-not (Test-Path $Sfx)) {
        $Sfx = Join-Path $Cache 'msys2-base-x86_64-latest.sfx.exe'
        Invoke-WebRequest 'https://github.com/msys2/msys2-installer/releases/latest/download/msys2-base-x86_64-latest.sfx.exe' -OutFile $Sfx
    }
    & $Sfx -y "-o$Cache" | Out-Null
}
if (-not (Test-Path (Join-Path $Msys 'ucrt64\bin\arm-none-eabi-gcc.exe'))) {
    Write-Host '>> compiler and QMK CLI'
    & $Bash -lc 'pacman -Sy --noconfirm --needed --disable-download-timeout git make diffutils mingw-w64-ucrt-x86_64-python-qmk mingw-w64-ucrt-x86_64-arm-none-eabi-gcc mingw-w64-ucrt-x86_64-arm-none-eabi-newlib mingw-w64-ucrt-x86_64-gcc'
}
New-Item -ItemType Directory -Force (Join-Path $Cache 'bin') | Out-Null
@'
#!/usr/bin/env python
# Keyglow's QMK CLI: the packaged one refuses MSYS2's UCRT64 Python by name only.
import sys
import qmk_cli.script_qmk as s
s.platform = lambda: 'msys2-ucrt64'   # skips only the terminal check in main()
sys.exit(s.main())
'@ | Set-Content -Encoding ascii -NoNewline (Join-Path $Cache 'bin\qmk')

# --- QMK --------------------------------------------------------------------------------------
$CacheU = Unix $Cache
if (-not (Test-Path (Join-Path $Cache 'qmk\keyboards\massdrop\alt'))) {
    Write-Host ">> QMK $QmkTag"
    & $Bash -lc "cd '$CacheU' && rm -rf qmk && git -c advice.detachedHead=false clone -q --depth 1 --branch $QmkTag https://github.com/qmk/qmk_firmware.git qmk && cd qmk && git submodule update -q --init --depth 1"
}

# --- mdloader ---------------------------------------------------------------------------------
if (-not (Test-Path (Join-Path $Cache 'mdloader\build\mdloader.exe'))) {
    Write-Host '>> mdloader'
    & $Bash -lc "export MSYSTEM=UCRT64; source /etc/profile; cd '$CacheU' && rm -rf mdloader && git clone -q https://github.com/Massdrop/mdloader.git && cd mdloader && git -c advice.detachedHead=false checkout -q $MdloaderCommit && make OS=Windows_NT CFLAGS='-Wall -std=gnu99 -static'"
}
Write-Host '>> ready'
