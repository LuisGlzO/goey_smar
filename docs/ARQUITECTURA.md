# Arquitectura técnica

## Flujo principal

1. Cada producto pertenece obligatoriamente a `amazon_a` o `amazon_b`.
2. Celery Beat agenda ambos scrapers con el mismo intervalo; `amazon_b` se publica con un desfase de medio intervalo.
3. Redis enruta cada tarea a `scraper_amazon_a` o `scraper_amazon_b`. Creators API usa `creators_api`.
4. Cada worker scraper tiene concurrencia uno y un perfil persistente exclusivo. Ambos pueden ejecutarse en paralelo.
5. Cada scraper procesa únicamente los productos activos de su partición. Creators API procesa todo el catálogo activo.
6. Todos los motores normalizan observaciones y usan el mismo servicio central de alertas y Telegram.
7. Las reservas transaccionales por producto coordinan detecciones simultáneas y evitan envíos duplicados.

## Identidad y exclusión

Las ejecuciones usan `scraper:amazon_a`, `scraper:amazon_b` y `creators_api:default`. Una ejecución vigente bloquea sólo otra con el mismo `worker_key`; las cuentas y Creators API pueden correr simultáneamente.

Cada perfil contiene `.goey-profile-owner`. El scraper valida este propietario antes de limpiar locks de Chromium. Un volumen montado en la cuenta equivocada falla sin abrir el navegador. La recuperación stale y los fallos consecutivos también se aíslan por `worker_key`.

## Seguridad

Los perfiles contienen sesiones autenticadas, están excluidos de Git y sólo se montan en su worker correspondiente. Django guarda únicamente alias operativos, nunca correos, contraseñas, cookies o rutas arbitrarias introducidas desde el panel.

`amazon_a` conserva el volumen histórico `amazon_profile`; `amazon_b` usa `amazon_profile_b`. El sistema no presiona botones ni modifica el carrito.

## Límites de responsabilidad

- `monitor/scraper.py`: perfil, navegación y conversión de HTML a observaciones.
- `monitor/services.py`: identidad de ejecución, auditoría y reglas centrales.
- `monitor/tasks.py`: entradas Celery parametrizadas por cuenta.
- `monitor/telegram.py`: único punto de integración con Telegram.
- Django: catálogo, asignación de cuenta y consulta operativa.
