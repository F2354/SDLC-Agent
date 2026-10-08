$ErrorActionPreference = 'Stop'

# Build the frontend and copy the output into backend/app/static so the
# backend can serve it as a single-origin app (used by dev preview and by
# the portable desktop packaging).

$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root 'frontend'
$backend = Join-Path $root 'backend'
$dist = Join-Path $frontend 'dist'
$static = Join-Path $backend 'app\static'

Write-Host 'Building frontend...' -ForegroundColor Cyan
Push-Location $frontend
try {
    if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
        Write-Host 'Installing frontend dependencies (npm install)...' -ForegroundColor Yellow
        npm install
    }
    npm run build
} finally {
    Pop-Location
}

if (-not (Test-Path $dist)) {
    throw "Frontend build output not found: $dist"
}

Write-Host 'Copying build output to backend/app/static ...' -ForegroundColor Cyan
if (Test-Path $static) {
    Remove-Item $static -Recurse -Force
}
New-Item -ItemType Directory -Path $static | Out-Null
Copy-Item (Join-Path $dist '*') $static -Recurse -Force

Write-Host "Done. Backend will now serve the frontend from: $static" -ForegroundColor Green
Write-Host 'Run the backend and open http://127.0.0.1:8000' -ForegroundColor Green
