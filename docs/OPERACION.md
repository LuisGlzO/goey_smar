# Manual de operación

## 1. Configuración

Copie `.env.example` a `.env`. Configure como mínimo:

- `DJANGO_SECRET_KEY`
- `POSTGRES_PASSWORD`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `AMAZON_ASSOCIATE_TAG`, identificador de seguimiento del programa de afiliados
- `AMAZON_SAVED_ITEMS_URL`, si la cuenta usa otro dominio de Amazon

El bot de Telegram debe ser administrador del canal privado de pruebas. Para un
canal, `TELEGRAM_CHAT_ID` suele tener formato `-100...`.

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

## 5. Validación inicial

Ejecute una revisión manual antes de activar la agenda:

```powershell
.\scripts\manage.ps1 monitor_saved_items
```

Revise `Monitor runs`, `Product checks` y `Alerts` en Django Admin. Los elementos
sin un ASIN activo se leen, pero no generan verificaciones ni alertas. Los ASIN
activos que no aparezcan en la página se registran con estado desconocido.

El monitor analiza únicamente los elementos dentro de la sección Guardado para
más tarde. Los productos del carrito activo no generan alertas.

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

Una alerta requiere disponibilidad y precio menor o igual al objetivo. Se permite
cuando es la primera disponibilidad, una reposición, una reducción significativa
o ya terminó el cooldown. Se aplican además el límite diario y la prevención de
duplicados durante cooldown.

## 9. Incidentes

- Ejecución fallida por sesión: regenere la sesión de Amazon.
- Selectores sin resultados: inspeccione cambios visuales de Amazon y ajuste
  `monitor/scraper.py`.
- Error Telegram: valide token, identificador del canal y permisos del bot.
- CAPTCHA frecuente: reduzca la frecuencia de monitoreo y use una sesión estable.
