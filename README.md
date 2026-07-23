# Goey SMAR

MVP de monitoreo de productos guardados para más tarde en Amazon, con validación
de precio, historial, reglas anti-spam y alertas automáticas a Telegram.

El sistema es únicamente de lectura: no mueve productos ni automatiza compras.

## Inicio rápido con Docker

1. Copiar `.env.example` a `.env` y completar credenciales.
2. Ejecutar `docker compose up --build -d`.
3. Crear el administrador:
   `docker compose exec web python manage.py createsuperuser`
4. Abrir `http://localhost:8000/admin/` y registrar productos.

La sesión persistente de Amazon debe prepararse antes de activar el worker. Una
sesión creada en Windows no debe asumirse compatible con el worker Linux de
Docker. Consulte [docs/OPERACION.md](docs/OPERACION.md) para ejecutar worker y
Beat localmente o preparar un despliegue completamente contenerizado.

## Entorno local

Requiere Python 3.12 x64, PostgreSQL y Redis. Python 3.12 es el runtime
recomendado para evitar problemas binarios con Playwright/greenlet en Windows.
Al ejecutar los servicios mediante
Docker, PostgreSQL queda disponible en `localhost:5433` y Redis en
`localhost:6379`:

```powershell
.\scripts\setup-local.ps1
.\.venv\Scripts\Activate.ps1
python manage.py createsuperuser
python manage.py collectstatic --noinput
python manage.py runserver
```

Para desarrollo o pruebas sin PostgreSQL, ejecute con `USE_SQLITE=true`.

Si instala manualmente con `pip install -r requirements.txt`, ejecute también:

```powershell
.\goey_smar_env\Scripts\playwright.exe install chromium
.\scripts\check-runtime.ps1
```

Si el entorno no está activado, use el lanzador incluido:

```powershell
.\scripts\manage.ps1 collectstatic --noinput
.\scripts\manage.ps1 init_amazon_session --account amazon_a
.\scripts\manage.ps1 monitor_saved_items --account amazon_a
```

El lanzador ejecuta `collectstatic` automáticamente al usar `runserver` si faltan
los estilos del admin.

## Verificación

```powershell
python manage.py check
python manage.py test
ruff check .
```

## Componentes

- Django Admin: productos, verificaciones, alertas y ejecuciones.
- Celery Beat: agenda revisiones periódicas.
- Celery Worker: ejecuta Playwright y publica alertas.
- PostgreSQL: configuración e historial de auditoría.
- Redis: cola de tareas.

## Automatización local

Con `db` y `redis` iniciados mediante Docker, ejecute en terminales separadas:

```powershell
.\scripts\celery.ps1 -A config worker -l INFO --pool=solo
.\scripts\celery.ps1 -A config beat -l INFO
```
