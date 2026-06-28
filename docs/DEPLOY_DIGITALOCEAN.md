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

En el firewall de DigitalOcean permita solo:

- SSH: `22/tcp`, idealmente desde su IP.
- HTTP: `80/tcp`, si usara dominio/HTTPS despues.
- HTTPS: `443/tcp`, si usara dominio/HTTPS despues.
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
DJANGO_ALLOWED_HOSTS=SERVER_PUBLIC_IP
DJANGO_CSRF_TRUSTED_ORIGINS=http://SERVER_PUBLIC_IP:8000
POSTGRES_PASSWORD=valor-largo-y-secreto
MONITOR_INTERVAL_SECONDS=60
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Si ya tiene dominio con HTTPS:

```env
DJANGO_ALLOWED_HOSTS=smar.cliente.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://smar.cliente.com
DJANGO_SESSION_COOKIE_SECURE=true
DJANGO_CSRF_COOKIE_SECURE=true
```

## 5. Levantar servicios

Para la primera prueba por IP/puerto:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Crear superusuario:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

Abrir:

```text
http://SERVER_PUBLIC_IP:8000/admin/
```

Cuando ya tenga dominio y HTTPS, ponga un proxy reverso delante del servicio
`web` y cierre el puerto `8000` en el firewall.

## 6. Revisar logs

```bash
docker compose -f docker-compose.prod.yml ps
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
