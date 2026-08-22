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

## Prueba local exclusiva de Discovery

El servicio `beat` es compartido: además del despachador de Discovery, programa los scrapers
Amazon A/B y Creators API del monitor comercial. Por tanto, **no inicie `beat`** durante una
prueba aislada de Discovery y no use `docker compose up` sin enumerar servicios.

### 1. Preparar configuración y base de datos

Configure `.env`, en especial las variables `DISCOVERY_*`, los límites por tipo de Amazon, el
perfil de Mercado Libre y los canales privados de Telegram. Luego construya e inicie solamente
la infraestructura y la aplicación web:

```bash
docker compose up -d --build db redis web
docker compose exec web python manage.py migrate
```

En Administración > Fuentes de descubrimiento, cree primero las fuentes como inactivas y ejecute
**Ejecutar diagnóstico**. Una ejecución satisfactoria debe indicar productos y páginas, pero debe
seguir mostrando `Is diagnostic = Sí` y no debe establecer el baseline.

### 2. Preparar Mercado Libre

Todas las fuentes Seller comparten el mismo perfil persistente. Si el perfil todavía no fue
inicializado, mantenga detenido su worker, ejecute en el host con interfaz gráfica:

```bash
python manage.py init_mercadolibre_discovery_session --url "https://listado.mercadolibre.com.mx/pagina/tieronezone/"
```

Confirme que el listado sea visible y presione Enter en la terminal. Este paso no se repite por
vendedor; solo se repite si Mercado Libre vuelve a solicitar verificación.

### 3. Iniciar exclusivamente los motores de Discovery

```bash
docker compose up -d --build worker_discovery worker_discovery_mercadolibre worker_discovery_notifications
```

`worker_discovery` procesa Top 100, Newest, Trackers y el propio despachador;
`worker_discovery_mercadolibre` procesa todos los vendedores secuencialmente; y
`worker_discovery_notifications` entrega únicamente notificaciones privadas de Discovery.

Compruebe que los tres estén activos:

```bash
docker compose ps worker_discovery worker_discovery_mercadolibre worker_discovery_notifications
```

### 4. Generar el baseline

Active únicamente las fuentes que desea probar. Una fuente nueva, activa y con `next_run_at`
vacío está vencida. Encole manualmente una pasada del despachador sin iniciar Beat:

```bash
docker compose exec web python manage.py shell -c "from monitor.tasks import dispatch_due_discovery_sources; print(dispatch_due_discovery_sources.delay().id)"
```

El despachador reserva todas las fuentes activas vencidas, actualiza su siguiente ejecución según
`interval_minutes` y enruta cada una a su cola. La primera ejecución **completa** de cada fuente:

- crea sus `DiscoveryProduct`;
- establece `baseline_established` y `baseline_established_at`;
- termina como `success`;
- no crea eventos ni notificaciones masivas.

Una ejecución `incomplete` o `failed` no establece baseline. Corrija la incidencia y repita el
despacho cuando la fuente vuelva a estar vencida. Para volverla ejecutable inmediatamente desde
el panel, deje `next_run_at` vacío; no elimine productos ni ejecuciones.

Observe el proceso en otra terminal:

```bash
docker compose logs -f worker_discovery worker_discovery_mercadolibre worker_discovery_notifications
```

En Administración verifique, para cada fuente, `Baseline established = Sí`, `Last status =
success` y una ejecución no diagnóstica (`Is diagnostic = No`). Revise también que la ejecución
del baseline tenga `Events created = 0` y `Notifications created = 0`.

### 5. Simular ejecuciones posteriores sin Beat

Para respetar exactamente `interval_minutes`, espere a que `next_run_at` venza y vuelva a ejecutar
el comando del despachador. Para una comprobación inmediata de todas las fuentes activas, sin
alterar su próxima fecha programada, puede encolar directamente una ejecución real por fuente:

```bash
docker compose exec web python manage.py shell -c "from monitor.models import DiscoverySource; from monitor.tasks import discovery_queue_for_source, run_discovery_source; sources=DiscoverySource.objects.filter(is_active=True); print([(s.pk, run_discovery_source.apply_async(args=(s.pk,), queue=discovery_queue_for_source(s)).id) for s in sources])"
```

Este comando **no es diagnóstico**: compara contra el baseline y puede crear eventos y enviar
mensajes a los canales privados si la fuente cambió. Antes de usarlo, confirme que los cuatro IDs
`TELEGRAM_*_CHANNEL_ID` apuntan a canales de prueba privados y nunca al canal comercial.

Al terminar la prueba aislada:

```bash
docker compose stop worker_discovery worker_discovery_mercadolibre worker_discovery_notifications
```

Detener los workers no elimina fuentes, baseline, productos ni historial.

### 6. Pasar a operación automática

En local, cuando también quiera ejecutar el monitor comercial, puede iniciar el conjunto completo:

```bash
docker compose up -d --build
```

En producción, después de configurar `.env`, preparar el perfil persistente de Mercado Libre y
aplicar migraciones, el equivalente es:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Ese comando también inicia `beat`; desde entonces el despachador revisa las fuentes vencidas cada
`DISCOVERY_DISPATCH_INTERVAL_SECONDS`, mientras cada fuente conserva su propio
`interval_minutes`. También inicia los workers y tareas periódicas del monitor comercial.

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
reutilizan un contexto efímero de Chromium exclusivo para descubrimiento. Este navegador es
público, no inicia sesión, no usa los perfiles de Amazon A/B y se cierra al terminar cada fuente.
Trackers acepta la URL de búsqueda construida por el cliente con sus palabras clave, filtros y
parámetros. Recorren la paginación visible,
extraen ASIN, nombre, precio y posición cuando están disponibles, y marcan la revisión como
incompleta ante bloqueos, CAPTCHA o estructuras inesperadas. En Trackers, un
ASIN nunca visto se registra y notifica aunque no tenga precio.

La profundidad de Amazon se configura por tipo mediante
`AMAZON_TOP100_DISCOVERY_MAX_PAGES`, `AMAZON_NEWEST_DISCOVERY_MAX_PAGES` y
`AMAZON_TRACKERS_DISCOVERY_MAX_PAGES`. `AMAZON_DISCOVERY_MAX_PAGES` se conserva como valor de
respaldo para instalaciones que todavía no definan las variables específicas. En Newest y
Trackers alcanzar la profundidad configurada representa una revisión completa del alcance
elegido: estos monitores solo descubren ASIN nuevos y no infieren ausencias. Top 100 conserva la
protección estricta y marca `page_limit` cuando todavía existe una página siguiente, porque una
revisión truncada podría producir salidas falsas. En fuentes Amazon `configuration` no permite
sobrescribir `max_pages`; `timeout_seconds` continúa disponible por fuente.

Mercado Libre Seller recorre el HTML público de la URL configurada mediante un perfil Chromium
persistente exclusivo de Discovery, usa el `wid` de la
publicación como identificador estable y extrae nombre, precio vigente y URL canónica. El API
oficial de búsqueda no se usa porque actualmente requiere un access token y las fuentes son URLs
públicas de vendedores ajenos. Un bloqueo, CAPTCHA, producto incompleto, ciclo o límite de
paginación marca la revisión como incompleta; por tanto no establece el baseline ni registra
ausencias. Una revisión completa registra ausencias sin notificarlas. Solo una publicación nunca
vista o una reducción igual o superior al umbral contra el último precio notificado crea una
notificación para `TELEGRAM_MERCADOLIBRE_CHANNEL_ID`.

Todas las fuentes Mercado Libre comparten el mismo perfil porque la sesión y las verificaciones
pertenecen al dominio, no al vendedor. Se enrutan a `MERCADOLIBRE_DISCOVERY_QUEUE` y el servicio
`worker_discovery_mercadolibre` las procesa secuencialmente con concurrencia 1; cada fuente
mantiene de todos modos ejecuciones, errores, baseline, productos y eventos independientes.
Nunca ejecute dos procesos contra el mismo `MERCADOLIBRE_DISCOVERY_PROFILE_DIR`.

Antes del primer diagnóstico, detenga `worker_discovery_mercadolibre` y, en una máquina con
interfaz gráfica, ejecute:

```bash
python manage.py init_mercadolibre_discovery_session \
  --url "https://listado.mercadolibre.com.mx/pagina/tieronezone/"
```

Resuelva la pantalla de seguridad, confirme que el listado sea visible, vuelva a la terminal y
presione Enter. Después inicie `worker_discovery_mercadolibre`. El directorio
`.mercadolibre-discovery-profile/` está ignorado por Git y se monta exclusivamente en ese worker;
debe tratarse como información sensible. Si Mercado Libre vuelve a solicitar verificación, la
corrida se registra como `captcha` y será necesario repetir la inicialización. Los fragmentos URL
que comienzan con `#` no se envían al servidor y se eliminan al guardar la fuente.

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
