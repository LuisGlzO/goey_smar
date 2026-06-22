$ErrorActionPreference = "Stop"

$pythonCommand = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        py -3.12 --version | Out-Null
        $pythonCommand = @("py", "-3.12")
    }
    catch {
        $pythonCommand = $null
    }
}

if (-not $pythonCommand -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $version = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($version -ne "3.12") {
        throw "Se recomienda Python 3.12 para evitar problemas binarios con Playwright/greenlet. Versión detectada: $version."
    }
    $pythonCommand = @("python")
}

if (-not $pythonCommand) {
    throw "Python 3.12 no está instalado o no está disponible. Instale Python 3.12 x64 y vuelva a ejecutar este script."
}

if ($pythonCommand.Count -eq 1) {
    & $pythonCommand[0] -m venv .venv
}
else {
    & $pythonCommand[0] $pythonCommand[1] -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements-dev.txt
& .\.venv\Scripts\playwright.exe install chromium
& .\.venv\Scripts\python.exe -c "import greenlet, playwright.sync_api; print('Runtime Playwright OK')"

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}

& .\.venv\Scripts\python.exe manage.py migrate
& .\.venv\Scripts\python.exe manage.py collectstatic --noinput
Write-Host "Entorno listo. Active con: .\.venv\Scripts\Activate.ps1"
