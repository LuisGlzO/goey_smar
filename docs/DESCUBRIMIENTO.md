# Monitores privados de descubrimiento

Este subsistema es deliberadamente independiente del catálogo comercial. Consulta fuentes
públicas mediante adaptadores de descubrimiento, conserva su propio historial y termina al
enviar una notificación al canal privado configurado. Nunca crea `Product`, `ProductCheck` ni
`Alert`, no ejecuta reglas comerciales y no publica en canales comerciales.

## Operación

Celery Beat ejecuta el despachador cada 60 segundos. Este reserva las fuentes activas vencidas
y publica una tarea por fuente en `discovery`, escalonándolas con
`DISCOVERY_STAGGER_SECONDS`. Cada fuente usa `interval_minutes` (30 por defecto). La restricción
de base de datos sobre ejecuciones `running` impide solapamientos y cada fallo queda en su
propio `DiscoveryRun`. Las tareas tienen caducidad y reintentos acotados.

La primera revisión completa establece un baseline y no genera notificaciones. Los eventos
posteriores crean una fila idempotente de `DiscoveryNotification`; el worker
`discovery_notifications` la entrega y registra `sent`, `failed`, el error y el ID de mensaje.

Canales privados por tipo:

- `TELEGRAM_TOP100_CHANNEL_ID`
- `TELEGRAM_NEWEST_CHANNEL_ID`
- `TELEGRAM_TRACKERS_CHANNEL_ID`
- `TELEGRAM_MERCADOLIBRE_CHANNEL_ID`

Se reutiliza `TELEGRAM_BOT_TOKEN` salvo que se configure `TELEGRAM_DISCOVERY_BOT_TOKEN`.
Todos los IDs anteriores deben corresponder a canales privados separados del canal comercial.
La entrega rechaza una configuración vacía y también rechaza expresamente cualquier ID que
coincida con `TELEGRAM_CHAT_ID`. El navegador acepta únicamente HTTPS, dominios oficiales del
proveedor, puerto HTTPS estándar sin credenciales y valida cada redirección antes de seguirla. No se
admiten hosts aportados por el usuario fuera de esas listas, lo que bloquea rutas SSRF hacia
localhost, direcciones privadas o servicios internos.

## Panel de operación

En Administración > Fuentes de descubrimiento se puede dar de alta una fuente por nombre y URL,
elegir el tipo, intervalo y porcentaje, y activarla o desactivarla. La lista muestra baseline,
último estado, última ejecución y última ejecución exitosa. Productos, ejecuciones, eventos y
notificaciones tienen búsquedas y filtros propios; los historiales son de solo lectura.

La acción **Ejecutar diagnóstico** funciona incluso sobre una fuente inactiva. Consulta la URL y
crea un `DiscoveryRun` marcado como diagnóstico con páginas, productos e incidencias, pero no
modifica `DiscoverySource.last_run`, baseline, productos, eventos ni notificaciones. Para una
primera revisión real, active la fuente y espere al despachador.

## Retención y observabilidad

`DISCOVERY_RETENTION_DAYS` (90) y `DISCOVERY_RETENTION_BATCH_SIZE` (5000) controlan la limpieza
diaria. Se eliminan en cascada ejecuciones terminadas antiguas, eventos y notificaciones; nunca
fuentes ni el estado actual de productos. Las ejecuciones en curso se preservan. Celery Beat
publica `cleanup_discovery_history` en la cola `discovery`.

Los workers emiten registros estructurados buscables `discovery_run_complete`,
`discovery_diagnostic_complete` y `discovery_cleanup_complete`, con IDs, estado y contadores.
Para operación rápida:

```bash
docker compose -f docker-compose.prod.yml logs -f worker_discovery worker_discovery_notifications
docker compose -f docker-compose.prod.yml exec web python manage.py showmigrations monitor
docker compose -f docker-compose.prod.yml exec web python manage.py check --deploy
```

Alertas recomendadas: fuente activa sin ejecución exitosa durante dos intervalos, ejecución
`failed`/`incomplete`, notificación `failed` o `processing` estancada, y crecimiento sostenido de
la cola `discovery_notifications`.

## Estado de conectores

Amazon Top 100, Amazon Newest y Amazon Trackers están habilitados mediante adaptadores que
reutilizan el navegador público común de Amazon. Trackers acepta la URL de búsqueda construida
por el cliente con sus palabras clave, filtros y parámetros. Recorren la paginación visible,
extraen ASIN, nombre, precio y posición cuando están disponibles, y marcan la revisión como
incompleta ante bloqueos, CAPTCHA, límites de página o estructuras inesperadas. En Trackers, un
ASIN nunca visto se registra y notifica aunque no tenga precio.

Mercado Libre Seller recorre el HTML público de la URL configurada, usa el `wid` de la
publicación como identificador estable y extrae nombre, precio vigente y URL canónica. El API
oficial de búsqueda no se usa porque actualmente requiere un access token y las fuentes son URLs
públicas de vendedores ajenos. Un bloqueo, CAPTCHA, producto incompleto, ciclo o límite de
paginación marca la revisión como incompleta; por tanto no establece el baseline ni registra
ausencias. Una revisión completa registra ausencias sin notificarlas. Solo una publicación nunca
vista o una reducción igual o superior al umbral contra el último precio notificado crea una
notificación para `TELEGRAM_MERCADOLIBRE_CHANNEL_ID`.

Los conectores se habilitan de forma independiente; una ejecución sin adaptador queda registrada
como fallida y no produce efectos comerciales.

Para iniciar localmente: `docker compose up --build`. Ejecute migraciones mediante el servicio
`web` y configure las variables anteriores en `.env`.

## Verificación de aislamiento comercial

Las funciones del flujo de descubrimiento importan exclusivamente modelos `Discovery*` y el
transporte Telegram genérico. No importan ni llaman `Product`, `ProductCheck`, `Alert`,
`run_monitor`, `run_creators_api_monitor`,
`evaluate_check` ni ninguna regla comercial. Sus únicas salidas de red son lecturas HTTPS de las
fuentes permitidas y Telegram hacia los cuatro IDs privados anteriores. La prueba de integración
crea baseline y eventos posteriores y comprueba que los contadores de `Product`, `ProductCheck`,
`Alert` y `MonitorRun` permanecen en cero.
