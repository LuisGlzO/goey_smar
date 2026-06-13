$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$candidates = @(
    (Join-Path $projectRoot ".venv\Scripts\celery.exe"),
    (Join-Path $projectRoot "goey_smar_env\Scripts\celery.exe")
)
$celery = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $celery) {
    throw "No se encontró Celery en un entorno virtual. Ejecute .\scripts\setup-local.ps1 primero."
}

Push-Location $projectRoot
try {
    & $celery @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

