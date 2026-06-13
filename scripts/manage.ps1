$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$candidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    (Join-Path $projectRoot "goey_smar_env\Scripts\python.exe")
)
$python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $python) {
    throw "No se encontró un entorno virtual. Ejecute .\scripts\setup-local.ps1 primero."
}

& $python (Join-Path $projectRoot "manage.py") @args
exit $LASTEXITCODE

