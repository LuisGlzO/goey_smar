# Deploy en DigitalOcean Droplet

Esta guia describe el MVP barato: un Droplet ejecutando Django, Celery, Beat,
PostgreSQL y Redis con Docker Compose.

## 1. Antes de crear el Droplet

Prepare:

- cuenta de DigitalOcean;
- llave SSH registrada en DigitalOcean;
- repositorio accesible desde el servidor;
- dominio o subdominio opcional, por ejemplo `smar.cliente.com`;
- token y chat de Telegram;
- cuenta de Amazon que se usara para leer carrito/guardados;
- una contrasena fuerte para PostgreSQL;
- una `DJANGO_SECRET_KEY` nueva y larga.

Para el MVP use un Droplet Ubuntu con al menos 2 GB de RAM. Playwright/Chromium
consume memoria y 1 GB puede quedar justo.

## 2. Crear el Droplet

Recomendado:

- Ubuntu LTS.
- Plan Basic de 2 GB RAM.
- Autenticacion por SSH key.
- Region cercana al cliente.

En el firewall de DigitalOcean permita:

- SSH: `22/tcp`, idealmente desde su IP.
- HTTP: `80/tcp`, requerido por Caddy/Let's Encrypt.
- HTTPS: `443/tcp`, requerido para el admin por dominio.
- Prueba por IP: `8000/tcp`, solo si va a entrar temporalmente por
  `http://IP:8000/admin/`.

No exponga PostgreSQL ni Redis al internet.

## 3. Instalar runtime en el servidor

Conectese por SSH:

```bash
ssh root@SERVER_PUBLIC_IP
```

Instale Docker y el plugin de Compose siguiendo la documentacion oficial de
Docker para Ubuntu. Al final valide:

```bash
docker --version
docker compose version
```

## 4. Subir el proyecto

Clone el repositorio en el servidor:

```bash
git clone REPO_URL /opt/goey_smar
cd /opt/goey_smar
```

Copie el ejemplo de variables:

```bash
cp .env.production.example .env
```

Edite `.env`:

```bash
nano .env
```

Minimo configure:

```env
DJANGO_SECRET_KEY=valor-largo-y-secreto
DJANGO_DEBUG=false
SITE_DOMAIN=goeysmar.tensoria.com.mx
DJANGO_ALLOWED_HOSTS=goeysmar.tensoria.com.mx
DJANGO_CSRF_TRUSTED_ORIGINS=https://goeysmar.tensoria.com.mx
DJANGO_SESSION_COOKIE_SECURE=true
DJANGO_CSRF_COOKIE_SECURE=true
POSTGRES_PASSWORD=valor-largo-y-secreto
MONITOR_INTERVAL_SECONDS=60
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

El registro DNS tipo `A` del dominio debe apuntar al IP publico del Droplet. Por
ejemplo:

```text
goeysmar.tensoria.com.mx -> SERVER_PUBLIC_IP
```

## 5. Levantar servicios

Levante los servicios:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Crear superusuario:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

Abrir:

```text
https://goeysmar.tensoria.com.mx/admin/
```

Caddy se encarga de solicitar y renovar automaticamente el certificado HTTPS.
El servicio `web` solo queda expuesto dentro de la red Docker; la entrada publica
debe ser `80/443` por el servicio `proxy`.

### Migrar desde la prueba por `:8000` al dominio

Si el admin ya funciona por `http://SERVER_PUBLIC_IP:8000/admin/`, haga:

1. Verifique que el DNS responde al IP del Droplet:

```bash
nslookup goeysmar.tensoria.com.mx
```

2. En el firewall de DigitalOcean, permita `80/tcp` y `443/tcp`.

3. En el Droplet, actualice `.env`:

```bash
cd ~/goey_smar
nano .env
```

Use:

```env
SITE_DOMAIN=goeysmar.tensoria.com.mx
DJANGO_ALLOWED_HOSTS=goeysmar.tensoria.com.mx
DJANGO_CSRF_TRUSTED_ORIGINS=https://goeysmar.tensoria.com.mx
DJANGO_SESSION_COOKIE_SECURE=true
DJANGO_CSRF_COOKIE_SECURE=true
```

4. Aplique el nuevo Compose con Caddy:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs --tail=80 proxy
```

5. Abra:

```text
https://goeysmar.tensoria.com.mx/admin/
```

Cuando el dominio funcione, quite `8000/tcp` del firewall. El puerto `8000` ya no
debe ser la entrada publica.

## 6. Revisar logs

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f proxy
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f worker
docker compose -f docker-compose.prod.yml logs -f beat
```

## 7. Configurar pausa por horario

En Django Admin abra `Configuracion del monitor`.

- `enabled=false` apaga el monitoreo sin detener el servidor.
- `active_from` y `active_until` limitan el horario.
- Si la ventana cruza medianoche, por ejemplo `23:00` a `07:00`, se interpreta
  como horario nocturno.

Fuera del horario permitido, la tarea queda como `Omitido` y no abre Amazon.

## 8. Sesion de Amazon

El worker usa el volumen Docker `amazon_profile` montado en
`/app/amazon-profile`. La sesion debe crearse en un ambiente compatible con el
Chromium Linux que usa el contenedor.

Para el MVP hay dos opciones:

- preparar una sesion desde el mismo servidor usando navegador remoto/VNC/Xvfb;
- copiar un perfil ya autenticado y probar si Chromium Linux lo acepta.

La primera opcion es mas estable para produccion. Si Amazon pide CAPTCHA o login,
las ejecuciones apareceran como fallidas en `Monitor runs`; en ese caso hay que
renovar la sesion.

### Iniciar o renovar sesion con noVNC temporal

Use este flujo cuando `worker` muestre errores como:

```text
La sesion de Amazon no es valida; ejecute init_amazon_session.
```

El navegador remoto solo queda disponible por tunel SSH local. No abra el puerto
`6080` al internet.

1. Desde su computadora, abra una terminal local con tunel SSH:

```bash
ssh -L 6080:127.0.0.1:6080 root@SERVER_PUBLIC_IP
```

2. Dentro del Droplet, vaya al proyecto y pause la automatizacion:

```bash
cd ~/goey_smar
docker compose -f docker-compose.prod.yml stop beat worker
```

3. Limpie locks anteriores del perfil de Chromium:

```bash
docker compose -f docker-compose.prod.yml run --rm worker sh -lc '
rm -f /app/amazon-profile/SingletonLock \
      /app/amazon-profile/SingletonSocket \
      /app/amazon-profile/SingletonCookie \
      /app/amazon-profile/DevToolsActivePort
'
```

4. Levante el navegador temporal con noVNC:

```bash
docker compose -f docker-compose.prod.yml run --rm --publish 127.0.0.1:6080:6080 worker sh -lc '
set -e
apt-get update
apt-get install -y --no-install-recommends xvfb fluxbox x11vnc novnc websockify x11-utils

rm -f /app/amazon-profile/SingletonLock \
      /app/amazon-profile/SingletonSocket \
      /app/amazon-profile/SingletonCookie \
      /app/amazon-profile/DevToolsActivePort

Xvfb :99 -screen 0 1366x768x24 >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99

for i in $(seq 1 20); do
  xdpyinfo -display :99 >/dev/null 2>&1 && break
  sleep 1
done

fluxbox >/tmp/fluxbox.log 2>&1 &
x11vnc -display :99 -forever -shared -nopw -listen 127.0.0.1 -xkb >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc/ 0.0.0.0:6080 127.0.0.1:5900 >/tmp/novnc.log 2>&1 &

python manage.py init_amazon_session
'
```

5. Cuando la terminal muestre que debe iniciar sesion, abra en su navegador local:

```text
http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale
```

6. En el navegador remoto:

- inicie sesion en Amazon;
- resuelva CAPTCHA si aparece;
- abra el carrito y la seccion Guardado para mas tarde;
- regrese a la terminal SSH y presione Enter para guardar/cerrar la sesion.

7. Pruebe una ejecucion manual:

```bash
docker compose -f docker-compose.prod.yml start worker
docker compose -f docker-compose.prod.yml exec worker python manage.py monitor_saved_items
```

Si responde con `Ejecucion X: N elementos visibles`, reactive la agenda:

```bash
docker compose -f docker-compose.prod.yml start beat
```

8. Revise logs y admin:

```bash
docker compose -f docker-compose.prod.yml logs --tail=80 worker
docker compose -f docker-compose.prod.yml logs --tail=80 beat
```

En Django Admin revise `Monitor runs`, `Product checks` y `Alerts`.

Si el navegador falla indicando que el perfil esta en uso, repita los pasos 2 y
3 antes de intentar de nuevo.

## 9. Operacion cotidiana

Actualizar codigo:

```bash
cd /opt/goey_smar
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Respaldar base de datos:

```bash
docker compose -f docker-compose.prod.yml exec db pg_dump -U goey_smar goey_smar > backup.sql
```

Detener todo:

```bash
docker compose -f docker-compose.prod.yml down
```

No use `down -v` salvo que quiera borrar los volumenes de PostgreSQL, Redis y el
perfil de Amazon.
