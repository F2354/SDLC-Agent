param(
    # Portable CPython (python-build-standalone "install_only" build, Windows x64).
    # Pinned for reproducible builds; override with -PythonUrl if needed.
    [string]$PythonUrl = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.12.15%2B20261003-x86_64-pc-windows-msvc-install_only.tar.gz'
)

$ErrorActionPreference = 'Stop'

# Build a portable (green) desktop app: frontend build + bundled Python runtime +
# Electron shell, packaged as an unpacked folder and a zip. No installer.

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$desktop = Join-Path $root 'desktop'
$runtime = Join-Path $desktop 'runtime'
$pythonDir = Join-Path $runtime 'python'
$backendCopy = Join-Path $runtime 'backend'
$releaseDir = Join-Path $desktop 'release'
$unpacked = Join-Path $releaseDir 'win-unpacked'
$zipDir = Join-Path $root 'release'
$zipPath = Join-Path $zipDir 'SDLC-Agent-portable-win-x64.zip'

Write-Host '=== [1/6] Build frontend (into backend/app/static) ===' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'build.ps1')

Write-Host '=== [2/6] Prepare portable Python runtime ===' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$pythonExe = Join-Path $pythonDir 'python.exe'
if (-not (Test-Path $pythonExe)) {
    $archive = Join-Path $env:TEMP 'sdlc-cpython-portable.tar.gz'
    Write-Host "Downloading portable Python from $PythonUrl" -ForegroundColor Yellow
    Invoke-WebRequest -Uri $PythonUrl -OutFile $archive -UseBasicParsing
    if (Test-Path $pythonDir) {
        Remove-Item $pythonDir -Recurse -Force
    }
    Write-Host 'Extracting portable Python...' -ForegroundColor Yellow
    # The archive contains a top-level 'python/' directory.
    tar -xzf $archive -C $runtime
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to extract portable Python (tar exit $LASTEXITCODE)"
    }
    Remove-Item $archive -Force
} else {
    Write-Host 'Portable Python already present, skipping download.' -ForegroundColor DarkGray
}
if (-not (Test-Path $pythonExe)) {
    throw "Portable Python not found at $pythonExe"
}

Write-Host '=== [3/6] Install backend dependencies into portable Python ===' -ForegroundColor Cyan
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r (Join-Path $backend 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw 'pip install failed'
}

Write-Host '=== [4/6] Copy backend source (excluding venv/data/caches) ===' -ForegroundColor Cyan
if (Test-Path $backendCopy) {
    Remove-Item $backendCopy -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $backendCopy | Out-Null
robocopy $backend $backendCopy /E /XD '.venv' 'data' '__pycache__' '.pytest_cache' 'tests' /XF '*.pyc' | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}

Write-Host '=== [5/6] Build Electron app (unpacked) ===' -ForegroundColor Cyan
Push-Location $desktop
try {
    npm install
    npm run dist
} finally {
    Pop-Location
}
if (-not (Test-Path $unpacked)) {
    throw "Electron build output not found: $unpacked"
}

Write-Host '=== [6/7] Create portable zip (folder distribution) ===' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $zipDir | Out-Null
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}
Compress-Archive -Path (Join-Path $unpacked '*') -DestinationPath $zipPath

Write-Host '=== [7/7] Build single-file portable exe (NSIS) ===' -ForegroundColor Cyan
$makensis = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'electron-builder\Cache\nsis') -Recurse -Filter 'makensis.exe' -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $makensis) {
    Write-Host 'NSIS not found, downloading...' -ForegroundColor Yellow
    $sevenZip = Join-Path $desktop 'node_modules\7zip-bin\win\x64\7za.exe'
    if (-not (Test-Path $sevenZip)) {
        throw '7za.exe not found. Run "npm install" in desktop first.'
    }
    $nsisArchive = Join-Path $env:TEMP 'nsis-3.0.4.1.7z'
    $nsisDir = Join-Path $env:LOCALAPPDATA 'electron-builder\Cache\nsis\nsis-3.0.4.1'
    Invoke-WebRequest 'https://github.com/electron-userland/electron-builder-binaries/releases/download/nsis-3.0.4.1/nsis-3.0.4.1.7z' -OutFile $nsisArchive -UseBasicParsing
    & $sevenZip x $nsisArchive "-o$nsisDir" -y | Out-Null
    $makensis = Get-ChildItem $nsisDir -Recurse -Filter 'makensis.exe' | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $makensis) {
    throw 'Unable to locate makensis.exe'
}
& $makensis (Join-Path $desktop 'installer\portable.nsi')
if ($LASTEXITCODE -ne 0) {
    throw 'makensis failed'
}
$singleExe = Join-Path $releaseDir 'SDLC-Agent.exe'

Write-Host ''
Write-Host 'Portable builds ready:' -ForegroundColor Green
Write-Host "  Single-file exe : $singleExe" -ForegroundColor Green
Write-Host "  Folder          : $unpacked" -ForegroundColor Green
Write-Host "  Zip             : $zipPath" -ForegroundColor Green
Write-Host 'Run the single-file exe directly (no installation required).' -ForegroundColor Green
