"""Middleware original sin restricciones adicionales por rol."""


def _noop_middleware(get_response):
    """Mantiene el comportamiento estándar de Django sin redirecciones por perfil."""

    def middleware(request):
        return get_response(request)

    return middleware


class WarehouseAdminAccessMiddleware:
    """Compatibilidad con proyectos anteriores: sin restricciones de acceso por rol."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)
