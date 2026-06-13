# Arquitectura técnica

## Flujo principal

1. Celery Beat agenda `monitor.tasks.monitor_saved_items`.
2. El worker abre la URL configurada usando un perfil persistente de Playwright.
3. El scraper extrae ASIN, texto, enlace, precio y señales de disponibilidad.
4. El servicio relaciona cada ASIN con los productos activos de PostgreSQL.
5. Cada resultado genera un `ProductCheck`; los productos no visibles quedan como
   estado desconocido.
6. La política evalúa precio objetivo, transición de estado, cooldown, reducción
   significativa y límite diario.
7. Se registra una alerta enviada, omitida o fallida y, cuando corresponde, se
   publica mediante Telegram Bot API.

## Límites de responsabilidad

- `monitor/scraper.py`: navegación y conversión de HTML a datos normalizados.
- `monitor/services.py`: auditoría, disponibilidad y reglas de alerta.
- `monitor/telegram.py`: único punto de integración con Telegram.
- `monitor/tasks.py`: entrada para procesamiento en segundo plano.
- Django Admin: gestión operativa y consulta del historial.

## Seguridad y operación

El perfil de Amazon contiene una sesión autenticada y debe tratarse como un
secreto. Está excluido de Git y solo debe montarse en el worker. El sistema no
presiona botones ni modifica el carrito.

El worker usa concurrencia uno para impedir que dos navegadores utilicen el mismo
perfil simultáneamente. Los cambios visuales de Amazon pueden requerir ajustes en
el scraper; las decisiones de alertas permanecen aisladas de esos ajustes.

