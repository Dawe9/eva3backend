# Dulce Arte: gestión de pedidos y producción de pastelería

Sistema interno Django/DRF para registrar pedidos, coordinar etapas de producción
y controlar los ingredientes de una pastelería artesanal.

## Entrega y acceso desplegado

- Repositorio público: <https://github.com/Dawe9/eva3backend>
- Aplicación con HTTPS: <https://dulceartes.duckdns.org>
- DNS A mostrado por DuckDNS al documentar el despliegue: `100.30.78.166`.
- La IPv4 pública asignada por AWS debe confirmarse en **EC2 → Instances →
  instancia → Public IPv4 address** antes de registrarla como IP de EC2. El
  valor `100.30.78.166` está en el rango compartido `100.64.0.0/10`; por eso se
  documenta como valor observado en DuckDNS, no como IPv4 pública de AWS.
- El navegador confirmó HTTPS activo para el dominio. Nginx termina TLS con
  Certbot/Let's Encrypt.

## Requisitos

- Python 3.12 o posterior compatible con `requirements.txt`.
- Git.
- Para despliegue: instancia Ubuntu en AWS EC2, Nginx, Gunicorn y un nombre
  DuckDNS apuntando a la instancia.

## Ejecución local en Windows CMD

Desde la carpeta del repositorio:

```cmd
py -m venv .venv
call .venv\Scripts\activate.bat
py -m pip install -r requirements.txt
py manage.py migrate
py manage.py seed_bakery_materials
py manage.py seed_bakery_products
py manage.py runserver
```

Abrir <http://127.0.0.1:8000/>. Para crear el primer usuario administrativo
local, ejecuta `py manage.py createsuperuser`.

Los comandos `seed_bakery_materials` y `seed_bakery_products` son idempotentes.
El catálogo contiene 22 ingredientes con stock inicial cero y diez tortas
comunes más la opción personalizada. Los precios de las tortas comunes son
sugerencias editables, no tarifas oficiales.

## Despliegue en AWS EC2 con Gunicorn, Nginx y DuckDNS HTTPS

### 1. DNS y grupo de seguridad

1. En DuckDNS, configura el registro `dulceartes` con la IPv4 pública actual de
   EC2. Una Elastic IP evita que cambie al detener/iniciar la instancia.
2. En el grupo de seguridad de EC2 permite TCP 22 solo desde tu IP y TCP 80/443
   desde Internet.
3. En Windows CMD verifica:

   ```cmd
   nslookup dulceartes.duckdns.org
   ```

   La respuesta debe corresponder al destino de DuckDNS. Confirma la dirección
   pública de EC2 separadamente en la consola AWS. Certbot necesita que el
   dominio llegue a esta instancia por el puerto 80.

### 2. Conexión desde Windows CMD

Reemplaza la IP por el valor **Public IPv4 address** que muestra AWS. La llave
utilizada en este despliegue está en el Escritorio:

```cmd
ssh -i "C:\Users\Andy\Desktop\svk.pem" ubuntu@<IP_PUBLICA_EC2>
```

Los pasos siguientes se ejecutan en la consola Ubuntu abierta por SSH.

### 3. Instalar paquetes y descargar el proyecto

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip nginx certbot python3-certbot-nginx
sudo adduser --system --group --home /srv/dulce-arte dulcearte
sudo chmod 755 /srv/dulce-arte
sudo -u dulcearte git clone https://github.com/Dawe9/eva3backend.git /srv/dulce-arte/app
sudo -u dulcearte python3 -m venv /srv/dulce-arte/app/.venv
sudo -u dulcearte /srv/dulce-arte/app/.venv/bin/pip install --upgrade pip
sudo -u dulcearte /srv/dulce-arte/app/.venv/bin/pip install \
  -r /srv/dulce-arte/app/requirements.txt gunicorn
```

### 4. Instalar la base SQLite inicial

`db_aws_catalog.sqlite3` contiene las migraciones y catálogos, pero no usuarios,
sesiones ni pedidos. La base activa se coloca fuera del repositorio:

```bash
sudo install -d -o dulcearte -g www-data -m 2770 /var/lib/dulce-arte
sudo install -o dulcearte -g www-data -m 660 \
  /srv/dulce-arte/app/db_aws_catalog.sqlite3 \
  /var/lib/dulce-arte/db.sqlite3
```

No reemplaces esta base durante actualizaciones: contiene el inventario y los
pedidos que se creen en producción. Realiza respaldos periódicos.

### 5. Variables de entorno

Genera una clave secreta y cópiala para el archivo de entorno:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
sudo nano /etc/dulce-arte.env
```

Contenido (reemplaza la clave; la IP es opcional en `ALLOWED_HOSTS`):

```ini
DJANGO_SECRET_KEY=PEGA_AQUI_LA_CLAVE_GENERADA
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=dulceartes.duckdns.org,<IP_PUBLICA_EC2>,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://dulceartes.duckdns.org
DJANGO_SECURE_COOKIES=true
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=/var/lib/dulce-arte/db.sqlite3
```

Protege el archivo:

```bash
sudo chown root:root /etc/dulce-arte.env
sudo chmod 600 /etc/dulce-arte.env
```

### 6. Migraciones, catálogos, estáticos y superusuario

```bash
sudo bash -c '
set -a
. /etc/dulce-arte.env
set +a
cd /srv/dulce-arte/app
sudo -u dulcearte env \
  DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" \
  DJANGO_DEBUG="$DJANGO_DEBUG" \
  DJANGO_ALLOWED_HOSTS="$DJANGO_ALLOWED_HOSTS" \
  DJANGO_CSRF_TRUSTED_ORIGINS="$DJANGO_CSRF_TRUSTED_ORIGINS" \
  DJANGO_SECURE_COOKIES="$DJANGO_SECURE_COOKIES" \
  DB_ENGINE="$DB_ENGINE" DB_NAME="$DB_NAME" \
  /srv/dulce-arte/app/.venv/bin/python manage.py migrate
sudo -u dulcearte env \
  DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" DJANGO_DEBUG="$DJANGO_DEBUG" \
  DJANGO_ALLOWED_HOSTS="$DJANGO_ALLOWED_HOSTS" \
  DJANGO_CSRF_TRUSTED_ORIGINS="$DJANGO_CSRF_TRUSTED_ORIGINS" \
  DJANGO_SECURE_COOKIES="$DJANGO_SECURE_COOKIES" \
  DB_ENGINE="$DB_ENGINE" DB_NAME="$DB_NAME" \
  /srv/dulce-arte/app/.venv/bin/python manage.py seed_bakery_materials
sudo -u dulcearte env \
  DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" DJANGO_DEBUG="$DJANGO_DEBUG" \
  DJANGO_ALLOWED_HOSTS="$DJANGO_ALLOWED_HOSTS" \
  DJANGO_CSRF_TRUSTED_ORIGINS="$DJANGO_CSRF_TRUSTED_ORIGINS" \
  DJANGO_SECURE_COOKIES="$DJANGO_SECURE_COOKIES" \
  DB_ENGINE="$DB_ENGINE" DB_NAME="$DB_NAME" \
  /srv/dulce-arte/app/.venv/bin/python manage.py seed_bakery_products
sudo -u dulcearte env \
  DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" DJANGO_DEBUG="$DJANGO_DEBUG" \
  DJANGO_ALLOWED_HOSTS="$DJANGO_ALLOWED_HOSTS" \
  DJANGO_CSRF_TRUSTED_ORIGINS="$DJANGO_CSRF_TRUSTED_ORIGINS" \
  DJANGO_SECURE_COOKIES="$DJANGO_SECURE_COOKIES" \
  DB_ENGINE="$DB_ENGINE" DB_NAME="$DB_NAME" \
  /srv/dulce-arte/app/.venv/bin/python manage.py collectstatic --noinput
sudo -u dulcearte env \
  DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" DJANGO_DEBUG="$DJANGO_DEBUG" \
  DJANGO_ALLOWED_HOSTS="$DJANGO_ALLOWED_HOSTS" \
  DJANGO_CSRF_TRUSTED_ORIGINS="$DJANGO_CSRF_TRUSTED_ORIGINS" \
  DJANGO_SECURE_COOKIES="$DJANGO_SECURE_COOKIES" \
  DB_ENGINE="$DB_ENGINE" DB_NAME="$DB_NAME" \
  /srv/dulce-arte/app/.venv/bin/python manage.py createsuperuser
'
```

`createsuperuser` solicita el nombre y la contraseña de acceso. No se guardan
credenciales en el repositorio ni en la base de catálogo compartida.

### 7. Servicio Gunicorn

```bash
sudo nano /etc/systemd/system/dulce-arte.service
```

```ini
[Unit]
Description=Dulce Arte Django Gunicorn
After=network.target

[Service]
User=dulcearte
Group=www-data
WorkingDirectory=/srv/dulce-arte/app
EnvironmentFile=/etc/dulce-arte.env
RuntimeDirectory=dulce-arte
RuntimeDirectoryMode=0750
UMask=0007
ExecStart=/srv/dulce-arte/app/.venv/bin/gunicorn --workers 3 --bind unix:/run/dulce-arte/gunicorn.sock academic_project.wsgi:application
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dulce-arte
sudo systemctl status dulce-arte --no-pager
```

### 8. Nginx y certificado HTTPS

```bash
sudo nano /etc/nginx/sites-available/dulce-arte
```

```nginx
server {
    listen 80;
    server_name dulceartes.duckdns.org;

    location /static/ {
        alias /srv/dulce-arte/app/staticfiles/;
    }

    location / {
        proxy_pass http://unix:/run/dulce-arte/gunicorn.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Activa el sitio y valida la configuración:

```bash
sudo ln -s /etc/nginx/sites-available/dulce-arte /etc/nginx/sites-enabled/dulce-arte
sudo nginx -t
sudo systemctl reload nginx
```

Cuando DuckDNS apunte a la IP pública actual de EC2 y el puerto 80 sea accesible,
solicita y prueba el certificado:

```bash
sudo certbot --nginx -d dulceartes.duckdns.org --redirect
sudo certbot renew --dry-run
```

### 9. Verificación y mantenimiento

- Aplicación: <https://dulceartes.duckdns.org>
- Login del equipo: <https://dulceartes.duckdns.org/login/>
- Django Admin: <https://dulceartes.duckdns.org/admin/>
- Gestión de pedidos e inventario: `/pedidos/` y `/inventario/`.

Para revisar errores:

```bash
sudo journalctl -u dulce-arte -n 100 --no-pager
sudo tail -n 100 /var/log/nginx/error.log
```

Al publicar cambios en GitHub, actualiza el código en EC2 con `git pull`, vuelve
a ejecutar `migrate` y `collectstatic` cuando corresponda y reinicia Gunicorn:

```bash
sudo systemctl restart dulce-arte
```

Los cambios hechos a la SQLite de producción no se sincronizan con GitHub.
Respalda `/var/lib/dulce-arte/db.sqlite3` periódicamente.

## API principal

- `GET /api/materiales/`: inventario de ingredientes.
- `/api/pedidos/`: pedidos con trazabilidad por etapa.
- `/api/pedidos/<id>/estado/`: cambio de etapa y consumo de ingredientes al completar producción.
- `/api/categorias/`, `/api/insumos/` y `/api/solicitudes/`: endpoints heredados.
- `/api/docs/`: documentación OpenAPI/Swagger, restringida a superusuario.
