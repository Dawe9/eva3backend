# Farmacia B2B - pedidos de insumos médicos

## Descripción

Aplicación Django para gestionar un catálogo médico institucional, el carrito de compras y el flujo de solicitudes de abastecimiento. La plataforma separa el acceso público del catálogo, la compra por parte de instituciones médicas y la operación del gestor de bodega.

## Funcionalidades principales

- Catálogo de insumos con filtros por categoría, nombre, lote y disponibilidad.
- Registro de instituciones médicas con usuarios autenticados por JWT.
- Carrito persistente por perfil de usuario y validación de sesión.
- Checkout con congelación de precios y creación de solicitudes transaccionales.
- Administración de inventario, estados de solicitud y control de stock por rol.
- API documentada con Swagger/OpenAPI y soporte para PostgreSQL o SQLite.

## Tecnologías

- Python 3.13+
- Django 6.1.1
- Django REST Framework
- Simple JWT
- django-filter
- drf-spectacular
- Bootstrap 5 y JavaScript nativo

## Instalación

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py manage.py migrate
```

## Carga de datos demo

```powershell
py manage.py seed_demo_supplies
```

Este comando crea categorías e insumos de ejemplo sin duplicar registros al ejecutarse nuevamente.

## Ejecución

```powershell
py manage.py runserver --insecure
```

`--insecure` permite servir los archivos estáticos del administrador durante el desarrollo local cuando `DEBUG` está desactivado. No debe usarse en producción. Abrir http://127.0.0.1:8000/.

## Rutas principales

- /: portada pública del catálogo.
- /products/: catálogo de insumos.
- /cart/: carrito persistente del usuario autenticado.
- /login/: inicio de sesión.
- /register/: alta de institución médica.
- /gestor/: panel del gestor de bodega.
- /api/token/ y /api/token/refresh/: autenticación JWT.
- /api/categorias/ y /api/insumos/: API pública y administrable.
- /api/carro-insumos/: gestión del carrito autenticado.
- /api/mis-solicitudes/: historial por institución.
- /api/solicitudes/<id>/estado/: cambio de estado de la solicitud.
- /api/docs/: documentación OpenAPI/Swagger.

## Notas del proyecto

El stock se descuenta al confirmar la solicitud de compra, y la cancelación de una solicitud pendiente o pagada repondrá el inventario dentro de la misma transacción. El pago solo cambia el estado de la solicitud y no vuelve a descontar inventario.

Consulta [GUIA_PROYECTO5.md](GUIA_PROYECTO5.md) para detalles del flujo de negocio, variables de entorno y pruebas del proyecto.
