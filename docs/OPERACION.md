# Manual de operación

## 1. Configuración

Copie `.env.example` a `.env`. Configure como mínimo:

- `DJANGO_SECRET_KEY`
- `POSTGRES_PASSWORD`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_ERROR_BOT_TOKEN`, bot para avisos tecnicos del monitor
- `TELEGRAM_ERROR_CHAT_ID`, canal para avisos tecnicos del monitor
- `AMAZON_ASSOCIATE_TAG`, identificador de seguimiento del programa de afiliados
- `AMAZON_SAVED_ITEMS_URL`, si la cuenta usa otro dominio de Amazon
- `MONITOR_FAILURE_EMAIL_RECIPIENTS`, correos que recibiran aviso si falla el scraper

El bot configurado en `TELEGRAM_BOT_TOKEN` debe poder publicar en el canal de
productos configurado en `TELEGRAM_CHAT_ID`; puede ser un ID `-100...` o un
username publico como `@canal_cliente`. Use `TELEGRAM_ERROR_BOT_TOKEN` y
`TELEGRAM_ERROR_CHAT_ID` para separar las alertas tecnicas de las alertas
normales de productos.

Para avisos por Gmail configure SMTP con una contrasena de aplicacion:

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=tu-correo@gmail.com
EMAIL_HOST_PASSWORD=tu-contrasena-de-aplicacion
DEFAULT_FROM_EMAIL=tu-correo@gmail.com
MONITOR_FAILURE_EMAIL_RECIPIENTS=operaciones@example.com
```

Los fallos se envian primero por Telegram con `TELEGRAM_ERROR_BOT_TOKEN` a
`TELEGRAM_ERROR_CHAT_ID`. Si Telegram falla y `MONITOR_FAILURE_EMAIL_RECIPIENTS`
esta configurado, se intenta email como respaldo. Sin configuracion completa de
Telegram para errores ni email de respaldo, el fallo queda registrado en
`Monitor runs` y en logs.
El aviso se dispara ante cualquier excepcion de la ejecucion, incluyendo sesion
invalida, CAPTCHA o login requerido.

Para evitar spam cuando el monitor corre cada minuto, las alertas tecnicas tienen
cooldown. Por default solo se envia una alerta de fallo por hora; cambielo con:

```env
MONITOR_FAILURE_ALERT_COOLDOWN_MINUTES=60
```

Para validar manualmente que el bot tecnico puede publicar en el canal de errores,
ejecute:

```powershell
.\scripts\manage.ps1 test_error_alert_channel --message "prueba manual"
```

En Docker/produccion:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py test_error_alert_channel --message "prueba manual"
```

Use Python 3.12 x64 para instalaciones locales en Windows. Si aparece
`DLL load failed while importing _greenlet`, recree el entorno con Python 3.12 y
ejecute `.\scripts\check-runtime.ps1`. Si persiste, instale Microsoft Visual C++
Redistributable 2015-2022 x64 y reinstale las dependencias.

Si el admin aparece sin estilos, ejecute:

```powershell
.\scripts\manage.ps1 collectstatic --noinput
```

Luego reinicie `runserver`. El lanzador prepara estos archivos automáticamente al
arrancar `runserver` cuando detecta que faltan.

## 2. Sesión de Amazon

En una instalación local con interfaz gráfica:

```powershell
.\scripts\manage.ps1 init_amazon_session
```

Inicie sesión manualmente, abra el carrito con la sección Guardado para más tarde
y presione Enter en la terminal. No comparta ni agregue el perfil generado al
repositorio.

Para servidor o Docker, genere el perfil en un entorno gráfico autorizado y
móntelo exclusivamente en `worker_scraper` como `/app/amazon-profile`. Amazon puede
invalidar sesiones o solicitar CAPTCHA; en ese caso hay que repetir este paso.

## 3. Productos

Abra `/admin/monitor/product/` y registre:

- ASIN de 10 caracteres
- nombre
- precio máximo
- prioridad
- cooldown y máximo de alertas diarias
- porcentaje considerado reducción significativa
- URL afiliada opcional, cuando el producto requiere un enlace específico

## 4. Enlaces de afiliado

Configure en `.env` el identificador entregado por Amazon Afiliados:

```env
AMAZON_ASSOCIATE_TAG=identificador-del-cliente
```

Las alertas generarán enlaces canónicos con el formato
`https://www.amazon.com.mx/dp/ASIN?tag=identificador`. Si un producto tiene una
URL afiliada específica en Django Admin, esa URL tendrá prioridad. Sin ninguna
de estas configuraciones, se enviará el enlace normal detectado en Amazon.

### Creators API para imagen y titulo

Para que la alerta de producto use la imagen principal y el titulo oficial de
Amazon, configure las credenciales de Creators API:

```env
AMAZON_CREATORS_API_CLIENT_ID=...
AMAZON_CREATORS_API_CLIENT_SECRET=...
AMAZON_CREATORS_API_CREDENTIAL_VERSION=3
AMAZON_CREATORS_API_MARKETPLACE=www.amazon.com.mx
AMAZON_CREATORS_API_PARTNER_TAG=goeygeeks2023-20
AMAZON_CREATORS_API_LANGUAGES=es_MX
AMAZON_CREATORS_API_TIMEOUT_SECONDS=5
```

Con credenciales v2.x use la version regional NA para Mexico, por ejemplo:

```env
AMAZON_CREATORS_API_CREDENTIAL_VERSION=2.1
```

Si Creators API no esta configurada, no devuelve el ASIN o falla temporalmente,
la alerta conserva el nombre local y el enlace afiliado ya configurado. Cuando la
API devuelve `detailPageURL`, esa URL se usa por default para conservar los
parametros de atribucion de Amazon; si el producto tiene una URL afiliada manual
en Django Admin, esa URL manual sigue teniendo prioridad. Cuando la API devuelve
imagen, Telegram envia la alerta como foto con el formato:

```text
🚨🚨🚨 Nombre del producto

https://www.amazon.com.mx/dp/ASIN?tag=...
```

La consulta a Creators API solo ocurre cuando una alerta se va a enviar. Si la
API no responde antes de `AMAZON_CREATORS_API_TIMEOUT_SECONDS`, se usa el
fallback local para no bloquear demasiado la corrida.

## 5. Validación inicial

Ejecute una revisión manual antes de activar la agenda:

```powershell
.\scripts\manage.ps1 monitor_saved_items
```

Revise `Monitor runs`, `Product checks` y `Alerts` en Django Admin. Los elementos
sin un ASIN activo se leen, pero no generan verificaciones ni alertas. Los ASIN
activos que no aparezcan en la página se registran con estado desconocido.

El monitor analiza los productos del carrito activo y los elementos dentro de la
sección Guardado para más tarde. El diagnóstico indica `source=cart` o
`source=saved` para saber de dónde salió cada lectura.

## 6. Ejecución automática local

Esta modalidad reutiliza directamente la sesión creada por
`init_amazon_session`. Mantenga PostgreSQL y Redis iniciados:

```powershell
docker compose up -d db redis
```

Después abra tres terminales. En la primera ejecute el worker del scraper:

```powershell
.\scripts\celery.ps1 -A config worker -l INFO --pool=solo -Q scraper -n scraper@%h
```

En la segunda ejecute el worker de Creators API:

```powershell
.\scripts\celery.ps1 -A config worker -l INFO --pool=solo -Q creators_api -n creators_api@%h
```

En la tercera ejecute el programador:

```powershell
.\scripts\celery.ps1 -A config beat -l INFO
```

Antes de este cambio, el worker local sin `-Q` consumía la cola predeterminada.
Ciérrelo y use los dos comandos anteriores; no debe mantenerse una cuarta
terminal con el comando antiguo.

Celery Beat agenda ambos motores según sus intervalos. Redis entrega el scraper a
la cola `scraper` y la API a `creators_api`, por lo que los dos workers pueden
ejecutarse al mismo tiempo y solicitar alertas al servicio central compartido.
Si el scraper pierde la sesión de Amazon, Creators API puede continuar trabajando
si su worker, Beat, Redis y PostgreSQL permanecen activos.
Las tareas publicadas por Beat expiran segun `MONITOR_TASK_EXPIRES_SECONDS`, por
lo que si una corrida tarda demasiado no se acumulan revisiones viejas para
ejecutarse inmediatamente despues.
Ademas, `MONITOR_TASK_TIME_LIMIT_SECONDS` define el limite duro de vida de una
tarea del worker.

Ante errores transitorios de infraestructura de Playwright/Chromium, como timeout
de navegacion o fallo al lanzar el navegador, el scraper reintenta con un
contexto nuevo. Configure:

```env
AMAZON_SCRAPER_MAX_ATTEMPTS=2
AMAZON_SCRAPER_RETRY_DELAY_SECONDS=5
```

Si se acumulan varios fallos consecutivos de infraestructura, el worker solicita
su propio reinicio para que Docker lo levante limpio con `restart:
unless-stopped`. Configure:

```env
MONITOR_INFRASTRUCTURE_FAILURE_RESTART_THRESHOLD=3
MONITOR_AUTO_RESTART_WORKER_ON_INFRA_FAILURE=true
```

Esto cubre casos como `pthread_create: Resource temporarily unavailable`,
`launch_persistent_context`, `Target page, context or browser has been closed` y
timeouts repetidos de `Page.goto`.

### Pausa por horario

Desde Django Admin abra `Configuracion del monitor`. Ahi puede:

- desactivar completamente el monitoreo con `enabled`;
- definir `active_from` y `active_until` para permitir revisiones solo en una
  ventana horaria local.
- configurar `Cooldown anti-falso-restock (minutos)`, un candado uniforme para
  todos los productos pero aplicado individualmente por producto. Si un producto
  ya envio alerta dentro de esa ventana, no vuelve a alertar hasta que termine.
  Use `0` para desactivarlo.

Si ambas horas estan vacias, el monitor queda activo todo el dia. Si la ventana
cruza medianoche, por ejemplo `23:00` a `07:00`, se interpreta como horario
nocturno. Fuera del horario permitido Celery Beat puede seguir disparando la
tarea, pero la ejecucion queda registrada como `Omitido` y no abre Amazon ni
Playwright.

### Solape de ejecuciones

Si una ejecucion del mismo `worker_key` sigue en estado `running` cuando entra
otra, la nueva se
registra como `Omitido` con razon `previous_run_still_running`. Esto evita que
dos scrapers usen simultaneamente el mismo perfil de Amazon. La variable
`MONITOR_RUNNING_STALE_MINUTES` define cuanto tiempo se considera valida una
ejecucion `running` antes de tratarla como stale.
Cuando entra una nueva ejecucion, cualquier `running` mas viejo que esa ventana
se marca automaticamente como `Fallido` con error `stale_run_recovered`.

Para recuperar manualmente ejecuciones viejas que ya quedaron en `running`:

```powershell
.\scripts\manage.ps1 recover_stale_monitor_runs
```

En Docker/produccion:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py recover_stale_monitor_runs
```

Si el proceso real del worker tambien quedo colgado, reinicie el servicio:

```bash
docker compose -f docker-compose.prod.yml restart worker_scraper
```

## 7. Docker Compose

`docker-compose.yml` describe seis servicios relacionados:

- `db`: PostgreSQL, almacena productos, verificaciones y alertas.
- `redis`: aloja las colas `scraper` y `creators_api`.
- `web`: Django Admin servido por Gunicorn.
- `beat`: programa verificaciones periódicas.
- `worker_scraper`: consume exclusivamente la cola Playwright y monta el perfil.
- `worker_creators`: consume exclusivamente la cola de Creators API.

`docker compose up -d db redis` inicia únicamente base y cola. `docker compose up
--build -d` intenta iniciar los seis servicios.
En producción, `docker compose -f docker-compose.prod.yml up -d --build` crea o
actualiza automáticamente ambos workers; no es necesario iniciarlos por separado.

La ejecución completamente dentro de Docker requiere preparar una sesión de
Amazon compatible dentro del volumen `amazon_profile`. Una sesión creada por el
navegador de Windows no debe asumirse compatible con Chromium Linux del
contenedor. Para la instalación local actual use la ejecución automática local
descrita arriba.

## 8. Criterios de alerta

Una alerta requiere que el scraper detecte forzosamente el botón de mover al
carrito y que el precio sea menor o igual al objetivo. Se permite cuando es la
primera disponibilidad, una reposición, una reducción significativa o ya terminó
el cooldown. Se aplican además el límite diario y la prevención de duplicados
durante cooldown.

## 9. Monitores y alertas manuales

El sistema ejecuta dos motores independientes: Playwright y Creators API. Ambos
registran verificaciones y solicitan el envío al mismo servicio central, por lo
que comparten cooldown anti-falso-restock, cooldown por producto y límite diario.
Configure la tarea API con `AMAZON_CREATORS_API_INTERVAL_SECONDS`,
`AMAZON_CREATORS_API_BATCH_SIZE` y `AMAZON_CREATORS_API_BATCH_DELAY_SECONDS`.

El panel web está disponible en `/` para usuarios de Django autenticados. Asigne
el permiso `monitor.send_manual_alert` al usuario o grupo que podrá abrir
`/alertas/` y publicar alertas manuales. Estas solicitudes no validan precio ni
stock, pero siempre respetan ambos cooldowns y el límite diario.

## 10. Gestión de productos

El módulo `/productos/` permite consultar, crear y editar productos fuera de
Django Admin. Asigne al grupo del cliente los permisos estándar
`monitor.view_product`, `monitor.add_product` y `monitor.change_product`. El
último habilita también la actualización masiva de cooldown y límite diario.

La fotografía se guarda como una URL devuelta por Creators API y se refresca
durante el monitor automático. No se almacenan archivos en el servidor, por lo
que no se requiere `MEDIA_ROOT`, un volumen Docker adicional ni DigitalOcean
Spaces. Después del despliegue, los productos existentes obtendrán su imagen en
la siguiente ejecución exitosa del monitor API.

## 11. Incidentes

- Ejecución fallida por sesión: regenere la sesión de Amazon.
- `pthread_create: Resource temporarily unavailable`: el contenedor o Droplet se
  quedo sin hilos/procesos o memoria mientras Chromium arrancaba. Reinicie
  `worker_scraper`, revise `docker stats`, `free -h`, `ps -eLf | wc -l` y considere subir
  RAM si se repite. El worker tambien intenta auto-recuperarse si el error se
  repite varias veces consecutivas.
- Selectores sin resultados: inspeccione cambios visuales de Amazon y ajuste
  `monitor/scraper.py`.
- Error Telegram: valide token, identificador del canal y permisos del bot.
- CAPTCHA frecuente: reduzca la frecuencia de monitoreo y use una sesión estable.
