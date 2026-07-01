# Manual de operación

## 1. Configuración

Copie `.env.example` a `.env`. Configure como mínimo:

- `DJANGO_SECRET_KEY`
- `POSTGRES_PASSWORD`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_ERROR_CHAT_ID`, canal alterno para avisos tecnicos si no se usa email
- `AMAZON_ASSOCIATE_TAG`, identificador de seguimiento del programa de afiliados
- `AMAZON_SAVED_ITEMS_URL`, si la cuenta usa otro dominio de Amazon
- `MONITOR_FAILURE_EMAIL_RECIPIENTS`, correos que recibiran aviso si falla el scraper

El bot de Telegram debe ser administrador del canal privado de pruebas. Para un
canal, `TELEGRAM_CHAT_ID` suele tener formato `-100...`. Use
`TELEGRAM_ERROR_CHAT_ID` para separar alertas tecnicas de las alertas normales
de productos; puede ser otro canal privado administrado por el mismo bot.

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

Si `MONITOR_FAILURE_EMAIL_RECIPIENTS` queda vacio, los fallos se envian por
Telegram a `TELEGRAM_ERROR_CHAT_ID`. Si el correo esta configurado pero falla,
tambien se intenta ese canal de Telegram como fallback. Sin email ni
`TELEGRAM_ERROR_CHAT_ID`, el fallo queda registrado en `Monitor runs` y en logs.
El aviso se dispara ante cualquier excepcion de la ejecucion, incluyendo sesion
invalida, CAPTCHA o login requerido.

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
móntelo exclusivamente en el worker como `/app/amazon-profile`. Amazon puede
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

Después abra dos terminales. En la primera ejecute el worker:

```powershell
.\scripts\celery.ps1 -A config worker -l INFO --pool=solo
```

En la segunda ejecute el programador:

```powershell
.\scripts\celery.ps1 -A config beat -l INFO
```

Celery Beat agenda una revisión según `MONITOR_INTERVAL_SECONDS`; Redis entrega
la tarea y el worker ejecuta Playwright, registra resultados y envía Telegram.
Las tareas publicadas por Beat expiran segun `MONITOR_TASK_EXPIRES_SECONDS`, por
lo que si una corrida tarda demasiado no se acumulan revisiones viejas para
ejecutarse inmediatamente despues.

### Pausa por horario

Desde Django Admin abra `Configuracion del monitor`. Ahi puede:

- desactivar completamente el monitoreo con `enabled`;
- definir `active_from` y `active_until` para permitir revisiones solo en una
  ventana horaria local.

Si ambas horas estan vacias, el monitor queda activo todo el dia. Si la ventana
cruza medianoche, por ejemplo `23:00` a `07:00`, se interpreta como horario
nocturno. Fuera del horario permitido Celery Beat puede seguir disparando la
tarea, pero la ejecucion queda registrada como `Omitido` y no abre Amazon ni
Playwright.

### Solape de ejecuciones

Si una ejecucion sigue en estado `running` cuando entra otra, la nueva se
registra como `Omitido` con razon `previous_run_still_running`. Esto evita que
dos scrapers usen simultaneamente el mismo perfil de Amazon. La variable
`MONITOR_RUNNING_STALE_MINUTES` define cuanto tiempo se considera valida una
ejecucion `running` antes de tratarla como stale.

## 7. Docker Compose

`docker-compose.yml` describe cinco servicios relacionados:

- `db`: PostgreSQL, almacena productos, verificaciones y alertas.
- `redis`: cola que comunica Beat con el worker.
- `web`: Django Admin servido por Gunicorn.
- `beat`: programa verificaciones periódicas.
- `worker`: ejecuta cada verificación.

`docker compose up -d db redis` inicia únicamente base y cola. `docker compose up
--build -d` intenta iniciar los cinco servicios.

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

## 9. Incidentes

- Ejecución fallida por sesión: regenere la sesión de Amazon.
- Selectores sin resultados: inspeccione cambios visuales de Amazon y ajuste
  `monitor/scraper.py`.
- Error Telegram: valide token, identificador del canal y permisos del bot.
- CAPTCHA frecuente: reduzca la frecuencia de monitoreo y use una sesión estable.
