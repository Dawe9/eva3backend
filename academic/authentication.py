"""Emisión de JWT con el rol RBAC del perfil del usuario."""

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Profile


class RoleTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Agrega rol e institución a los claims access y refresh."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        profile, _ = Profile.objects.get_or_create(
            user=user,
            defaults={
                'role': (
                    Profile.Role.WAREHOUSE_MANAGER
                    if user.is_staff
                    else Profile.Role.MEDICAL_INSTITUTION
                )
            },
        )
        expected_role = (
            Profile.Role.WAREHOUSE_MANAGER
            if user.is_staff
            else Profile.Role.MEDICAL_INSTITUTION
        )
        if profile.role != expected_role:
            profile.role = expected_role
            profile.save(update_fields=['role'])
        token['role'] = profile.role
        token['institution_id'] = profile.institution_id
        token['is_superuser'] = user.is_superuser
        return token


class RoleTokenObtainPairView(TokenObtainPairView):
    serializer_class = RoleTokenObtainPairSerializer