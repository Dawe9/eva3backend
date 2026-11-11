# Registro de apoyo de herramientas de IA

Este archivo resume solicitudes reales de asistencia con IA realizadas durante
la adaptación y validación de Dulce Arte. No contiene contraseñas, tokens ni
claves privadas.

## Adaptación funcional

- **Solicitud:** adaptar el proyecto existente a los requerimientos del caso de
  una pastelería y validar la aplicación frente a ellos.
- **Apoyo aplicado:** revisión del código y de los requerimientos; adaptación de
  la página principal a un panel de operaciones interno.
- **Solicitud:** separar la gestión de inventario y pedidos de la navegación
  general del Django Admin.
- **Apoyo aplicado:** creación de páginas propias para inventario y pedidos,
  con acceso restringido al personal autorizado.
- **Solicitud:** incorporar ingredientes comunes de pastelería y opciones
  habituales de tortas, incluyendo una opción personalizada.
- **Apoyo aplicado:** comandos idempotentes de carga inicial, migraciones,
  formularios y campos condicionales.
- **Solicitud:** investigar precios referenciales y permitir editarlos.
- **Apoyo aplicado:** precios sugeridos editables, documentados como
  estimaciones, junto con su fuente de referencia.

## Validación de negocio y permisos

- **Solicitud:** impedir fechas de entrega anteriores al día actual.
- **Apoyo aplicado:** validación en servidor, límite mínimo en el selector y
  prueba automatizada.
- **Solicitud:** probar el descuento de stock al comprar y al completar la
  producción.
- **Apoyo aplicado:** ejecución de pruebas de checkout y BOM; prueba adicional
  de descuento de ingredientes al pasar el pedido a “Listo”.
- **Solicitud:** permitir al personal avanzar etapas, sin acceso del staff al
  Django Admin.
- **Apoyo aplicado:** permiso de staff para el avance de etapas y restricción de
  la interfaz Django Admin a superusuarios.

## Entrega y despliegue

- **Solicitud:** publicar los cambios y una base SQLite que no incluya usuarios.
- **Apoyo aplicado:** verificación de tablas sensibles vacías, pruebas del
  proyecto, commit y publicación en GitHub.
- **Solicitud:** documentar el despliegue en AWS EC2 usando Gunicorn, Nginx y
  DuckDNS con HTTPS.
- **Apoyo aplicado:** instrucciones para CMD de Windows y Ubuntu, configuración
  de servicio, estáticos, base SQLite, Certbot y respaldos.
- **Solicitud:** contrastar los entregables con la pauta de evaluación.
- **Apoyo aplicado:** revisión del repositorio, README, registro de IA, URL HTTPS
  y distinción entre el valor DNS observado y la IPv4 pública que debe
  verificarse en la consola AWS.

## Herramientas utilizadas

- Asistente de IA en VS Code para análisis y edición del código.
- Django management commands para migraciones, catálogos y pruebas.
- Git y GitHub para control de versiones y publicación.
- Navegador para comprobaciones de las páginas y del acceso HTTPS.
