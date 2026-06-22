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

if ($args.Count -gt 0 -and $args[0] -eq "runserver") {
    $staticRoot = Join-Path $projectRoot "staticfiles"
    $adminCss = Join-Path $staticRoot "admin\css\base.css"
    if (-not (Test-Path $adminCss)) {
        Write-Host "Preparando archivos estáticos de Django Admin..."
        & $python (Join-Path $projectRoot "manage.py") collectstatic --noinput
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
}

& $python (Join-Path $projectRoot "manage.py") @args
exit $LASTEXITCODE
