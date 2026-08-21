$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

Start-Process -WindowStyle Hidden -FilePath 'python' -ArgumentList '-m','uvicorn','app.main:app','--reload','--port','8000' -WorkingDirectory $backend
Start-Process -WindowStyle Hidden -FilePath 'npm.cmd' -ArgumentList 'run','dev' -WorkingDirectory $frontend

Write-Host 'Backend: http://127.0.0.1:8000'
Write-Host 'Frontend: http://127.0.0.1:5173'
