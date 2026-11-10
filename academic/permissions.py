"""Permisos basados en el rol persistido del perfil autenticado."""

from rest_framework.permissions import BasePermission

from .models import Profile


class IsSuperUser(BasePermission):
    """Restringe la administración completa a superusuarios."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsStaffUser(BasePermission):
    """Permite operaciones internas a usuarios activos del personal."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
        )


class IsWarehouseManager(BasePermission):
    """Permite gestionar inventario y solicitudes al gestor de bodega."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
            and Profile.objects.filter(
                user=request.user,
                role=Profile.Role.WAREHOUSE_MANAGER,
            ).exists()
        )


class IsWarehouseManagerOrSuperUser(BasePermission):
    """Permite a gestores de bodega y superusuarios administrar inventario y solicitudes."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_superuser or IsWarehouseManager().has_permission(request, view)


class IsMedicalInstitution(BasePermission):
    """Limita carros y solicitudes a cuentas de instituciones médicas."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and not request.user.is_staff
            and Profile.objects.filter(
                user=request.user,
                role=Profile.Role.MEDICAL_INSTITUTION,
            ).exists()
        )