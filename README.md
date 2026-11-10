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
```

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
