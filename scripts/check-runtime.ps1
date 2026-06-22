$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$candidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    (Join-Path $projectRoot "goey_smar_env\Scripts\python.exe")
)
$python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $python) {
    throw "No se encontró un entorno virtual. Ejecute .\scripts\setup-local.ps1 o cree el entorno antes de continuar."
}

& $python -c @"
import sys
print('Python:', sys.version)
try:
    import django
    print('Django:', django.get_version())
    import greenlet
    print('greenlet:', greenlet.__version__)
    import playwright.sync_api
    print('Playwright import: OK')
except Exception as exc:
    print('Runtime import failed:', repr(exc))
    raise
"@

& (Join-Path (Split-Path $python) "playwright.exe") install chromium

