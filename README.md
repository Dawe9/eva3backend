# Proyecto 3: Sistema de Trazabilidad y Gestión de Pedidos para Pastelería Artesanal (Dulce Arte)

## Contexto y problema

La pastelería artesanal Dulce Arte presenta problemas de coordinación entre la toma de pedidos personalizados en el área de ventas, la disponibilidad de insumos en bodega y los tiempos de elaboración en cocina. Esto resulta en entregas tardías, desperdicio de insumos perecibles y errores en la preparación de recetas específicas.

## Objetivo general

Implementar un sistema de trazabilidad end-to-end para pedidos personalizados que conecta la cotización inicial, la planificación de producción en cocina (BOM) y la logística de entrega final.

## Funcionalidades clave y alcance

- Cotización y registro de pedidos personalizados (ingredientes, diseño, fecha/hora de entrega).
- Tablero Kanban digital para el taller de cocina (Recibido, En Preparación, Horneado, Decorado, Control de Calidad, Listo).
- Descuento automático de insumos en inventario mediante listas de materiales (BOM - Bill of Materials).
- Gestión de rutas de despacho con confirmación mediante firma digital o comprobante fotográfico.

La aplicación sigue la base tecnológica Django + DRF ya presente en este repositorio y se amplió para soportar nuevos modelos de pedido, inventario y trazabilidad de producción sin romper el flujo original del proyecto.

## Instalación

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py manage.py migrate
py manage.py seed_bakery_materials
py manage.py seed_bakery_products
```

El comando `seed_bakery_materials` crea un catálogo inicial de 22 ingredientes
habituales (harinas, azúcares, huevos, lácteos, chocolates y otros). El stock
inicial queda en cero; los mínimos son umbrales de alerta, no existencias
inventadas. El comando es idempotente y conserva las cantidades de materiales
que ya existan.

El comando `seed_bakery_products` agrega diez opciones de tortas comunes y una
opción independiente de `Torta personalizada`. El nombre, los detalles de
decoración y la descripción general solo se solicitan al seleccionar esa opción.
Las opciones comunes reciben un precio sugerido editable al crear el pedido; se
pueden ajustar en el precio unitario de cada línea o en el catálogo de tortas del
Admin. Son referencias para tortas estándar de aproximadamente 15 porciones,
no una tarifa oficial: Santa Isabel publica una torta de frambuesa de 15
porciones a $13.990 y su catálogo muestra tortas hasta $18.990 ([catálogo de
tortas](https://www.santaisabel.cl/busqueda?ft=torta)). Tamaño, decoración,
ingredientes y ubicación pueden cambiar el precio; la opción personalizada no
recibe un precio sugerido.

## Ejecución

```powershell
py manage.py runserver
```

## Endpoints principales

- /api/materiales/: inventario de ingredientes.
- /api/pedidos/: pedidos personalizados con trazabilidad por etapa.
- /api/pedidos/<id>/estado/: actualización del estado del pedido en el tablero Kanban.
- /api/categorias/, /api/insumos/ y /api/solicitudes/: flujos heredados del proyecto base y compatibles con la versión original.
- /api/docs/: documentación OpenAPI/Swagger.

## Nota

El repositorio mantiene compatibilidad con la versión anterior del proyecto de abastecimiento, pero ahora incorpora la lógica de producción artesanal y el control de materiales que exige el nuevo negocio.

## Base SQLite para importar

`db_aws_catalog.sqlite3` es una base SQLite sin cuentas de usuario, con las
migraciones del proyecto aplicadas y el catálogo inicial de pastelería. Para
usar ese archivo en un servidor, configura `DB_ENGINE=django.db.backends.sqlite3`
y `DB_NAME` con la ruta absoluta al archivo. Crea la cuenta de administración
en el servidor con `py manage.py createsuperuser`; no se incluyen usuarios ni
contraseñas en la base compartida.

SQLite sirve para una evaluación de una sola instancia, pero sus cambios no se
sincronizan automáticamente a GitHub y pueden perderse al reemplazar el archivo
durante un despliegue. Para un entorno AWS persistente o con varias instancias,
usa PostgreSQL y ejecuta `migrate` y `seed_bakery_materials` contra esa base.
