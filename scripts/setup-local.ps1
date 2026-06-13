$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.12+ no está instalado o no está disponible en PATH."
}

python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements-dev.txt
& .\.venv\Scripts\playwright.exe install chromium

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}

& .\.venv\Scripts\python.exe manage.py migrate
& .\.venv\Scripts\python.exe manage.py collectstatic --noinput
Write-Host "Entorno listo. Active con: .\.venv\Scripts\Activate.ps1"
