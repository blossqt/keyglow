# Builds Keyglow's firmware and packages the app into dist\Keyglow\Keyglow.exe, with Drop's loader
# (mdloader) in dist\Keyglow\tools and Keyglow Lights (the memory's lights; needs the .NET 10 SDK)
# in dist\Keyglow\lights.
#
#   powershell -ExecutionPolicy Bypass -File build\build_app.ps1
#
# Needs bootstrap.ps1.

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$Root  = Split-Path -Parent $PSScriptRoot
$Cache = Join-Path $env:LOCALAPPDATA 'KeyglowBuild'
$Py    = Join-Path $Cache 'venv\Scripts\python.exe'
$Bash  = Join-Path $Cache 'msys64\usr\bin\bash.exe'
$Loader = Join-Path $Cache 'mdloader\build\mdloader.exe'
$Dist  = Join-Path $Root 'dist\Keyglow'

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Py)) { Fail 'venv missing - run build\bootstrap.ps1 first' }
if (-not (Test-Path $Loader)) { Fail 'mdloader missing - run build\bootstrap.ps1 first' }
# PyInstaller empties dist\Keyglow first and stops at the first file in use.
$Exe = Join-Path $Dist 'Keyglow.exe'
$Running = Get-CimInstance Win32_Process -Filter "Name='Keyglow.exe'" -ErrorAction SilentlyContinue |
    Where-Object { "$($_.ExecutablePath)" -like "*$Exe*" }
if ($Running) { Fail "Keyglow is running from $Dist - close it first" }

Write-Host '>> firmware'
$Fw = '/' + $Root.Substring(0, 1).ToLower() + ($Root.Substring(2) -replace '\\', '/') + '/firmware/build.sh'
& $Bash -lc "export HOME=/c/Users/$env:USERNAME; bash '$Fw'"
if ($LASTEXITCODE -ne 0) { Fail 'the firmware did not build' }

Write-Host '>> import check'
& $Py -c "import sys; sys.path.insert(0, r'$Root\app'); import keyglow.app, keyglow.ui.window"
if ($LASTEXITCODE -ne 0) { Fail 'Keyglow does not import - fix the error above' }

Write-Host '>> icon'
& $Py (Join-Path $PSScriptRoot 'make_icon.py')
if ($LASTEXITCODE -ne 0) { Fail 'icon generation failed' }

Write-Host '>> PyInstaller'
Push-Location $Root
& $Py -m PyInstaller --noconfirm --clean --distpath (Join-Path $Root 'dist') `
    --workpath (Join-Path $Cache 'pyinstaller') (Join-Path $PSScriptRoot 'keyglow.spec')
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail "PyInstaller failed ($code)" }
if (-not (Test-Path $Exe)) { Fail 'Keyglow.exe was not produced' }

Write-Host '>> Drop''s loader'
New-Item -ItemType Directory -Force (Join-Path $Dist 'tools') | Out-Null
Copy-Item $Loader (Join-Path $Dist 'tools\mdloader.exe') -Force
Copy-Item (Join-Path $Cache 'mdloader\LICENSE') (Join-Path $Dist 'tools\mdloader-LICENSE.txt') -Force
Copy-Item (Join-Path $Cache 'mdloader\LICENSE_ATMEL') (Join-Path $Dist 'tools\mdloader-LICENSE_ATMEL.txt') -Force
foreach ($Doc in 'README.md', 'LICENSE', 'THIRD-PARTY-NOTICES.md') { Copy-Item (Join-Path $Root $Doc) $Dist -Force }

# Keyglow Lights - the memory's lights - goes beside it: the service and its setup.
Write-Host '>> Keyglow Lights'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'lights\build.ps1') -Out (Join-Path $Dist 'lights')
if ($LASTEXITCODE -ne 0) { Fail 'Keyglow Lights did not build' }

# Does it start? --self-test makes and draws the window (unseen) and finds a stand-in keyboard.
$Answer = Join-Path $env:TEMP "keyglow-self-test-$PID.txt"
Remove-Item $Answer -ErrorAction SilentlyContinue
$Probe = Start-Process -FilePath $Exe -ArgumentList '--self-test', "`"$Answer`"" -PassThru
if (-not $Probe.WaitForExit(120000)) { $Probe.Kill(); Fail 'the built Keyglow.exe hung when started (--self-test)' }
$Said = if (Test-Path $Answer) { (Get-Content -Raw $Answer).Trim() } else { '' }
Remove-Item $Answer -ErrorAction SilentlyContinue
if (-not $Said) { Fail 'the built Keyglow.exe does not start (--self-test gave no answer)' }
if ($Said.StartsWith('FAILED')) { Fail "the built Keyglow.exe starts but its self-test failed: $Said" }
Write-Host ">> it starts: Keyglow $Said"

$size = (Get-ChildItem $Dist -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ('>> done: {0}  ({1:N0} MB)' -f $Exe, ($size / 1MB))
