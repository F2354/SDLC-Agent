$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

# 优先使用 backend/.venv 中的解释器，避免依赖装进虚拟环境后启动失败。
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = 'python'
}

$venvUvicorn = Join-Path $backend '.venv\Scripts\uvicorn.exe'
if (Test-Path $venvUvicorn) {
    Start-Process -WindowStyle Hidden -FilePath $venvUvicorn -ArgumentList 'app.main:app','--reload','--port','8000' -WorkingDirectory $backend
} else {
    Start-Process -WindowStyle Hidden -FilePath $python -ArgumentList '-m','uvicorn','app.main:app','--reload','--port','8000' -WorkingDirectory $backend
}

Start-Process -WindowStyle Hidden -FilePath 'npm.cmd' -ArgumentList 'run','dev' -WorkingDirectory $frontend

Write-Host 'Backend:  http://127.0.0.1:8000'
Write-Host 'Frontend: http://127.0.0.1:5173'
Write-Host '首次运行请先完成 README「首次安装」步骤。'
