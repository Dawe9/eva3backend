"""Serializers de catálogo, carro y solicitudes de abastecimiento."""

import re

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import (
    Cart,
    CartItem,
    MedicalSupply,
    Institution,
    Profile,
    PurchaseRequest,
    PurchaseRequestItem,
    SupplyCategory,
)


class InstitutionRegistrationSerializer(serializers.Serializer):
    """Valida y crea una cuenta institucional sin aceptar roles del cliente."""

    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)
    password_confirm = serializers.CharField(min_length=8, write_only=True)
    institution_name = serializers.CharField(max_length=180, required=False, allow_blank=True)
    tax_id = serializers.CharField(max_length=20, required=False, allow_blank=True)
    birth_date = serializers.DateField(required=False, allow_null=True)

    def validate_username(self, value):
        if get_user_model().objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('Este nombre de usuario ya está registrado.')
        return value

    def validate_email(self, value):
        if get_user_model().objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('Este correo electrónico ya está registrado.')
        return value

    def validate_tax_id(self, value):
        value = value.strip().upper()
        if not value:
            return value

        compact_value = value.replace('.', '').replace('-', '')
        if not re.fullmatch(r'\d{1,8}[0-9K]', compact_value):
            raise serializers.ValidationError(
                'Ingresa un RUT válido con hasta 8 dígitos y un dígito verificador.'
            )

        body, verifier = compact_value[:-1], compact_value[-1]
        grouped_body = re.sub(r'\B(?=(\d{3})+(?!\d))', '.', body)
        return f'{grouped_body}-{verifier}'

    def validate_institution_name(self, value):
        value = value.strip()
        if value and Institution.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError('Esta institución ya está registrada.')
        return value

    def validate_birth_date(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError('La fecha de nacimiento no puede ser futura.')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Las contraseñas no coinciden.'})
        return attrs

    def create(self, validated_data):
        user_model = get_user_model()
        with transaction.atomic():
            tax_id = validated_data.get('tax_id', '').strip()
            institution_name = validated_data.get('institution_name', '').strip()
            institution = None
            if not institution_name and tax_id:
                institution = Institution.objects.filter(tax_id=tax_id).first()
            if institution is None:
                institution_name = institution_name or (
                    f'Institución {tax_id}' if tax_id else f"Institución de {validated_data['username']}"
                )
                institution, _ = Institution.objects.get_or_create(
                    name=institution_name,
                    defaults={'tax_id': tax_id},
                )
            user = user_model.objects.create_user(
                username=validated_data['username'],
                email=validated_data['email'],
                password=validated_data['password'],
            )
            Profile.objects.create(
                user=user,
                institution=institution,
                role=Profile.Role.MEDICAL_INSTITUTION,
                birth_date=validated_data.get('birth_date'),
            )
        return user


class SupplyCategorySerializer(serializers.ModelSerializer):
    """Valida y representa las categorías públicas del catálogo."""

    class Meta:
        model = SupplyCategory
        fields = ['id', 'name', 'description']


class MedicalSupplySerializer(serializers.ModelSerializer):
    """Expone trazabilidad del insumo y permite al gestor editar inventario."""

    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = MedicalSupply
        fields = [
            'id', 'category', 'category_name', 'commercial_name', 'active_ingredient',
            'lot', 'expiration_date', 'unit_price', 'image_url', 'stock', 'is_active',
        ]


class StockRestockSerializer(serializers.Serializer):
    """Valida la cantidad de cajas que se agregarán al inventario."""

    quantity = serializers.IntegerField(min_value=1)


class CartItemSerializer(serializers.ModelSerializer):
    """Representa cantidades del carro junto al precio vigente y su subtotal."""

    supply_name = serializers.CharField(source='supply.commercial_name', read_only=True)
    lot = serializers.CharField(source='supply.lot', read_only=True)
    unit_price = serializers.DecimalField(source='supply.unit_price', max_digits=12, decimal_places=2, read_only=True)
    available_stock = serializers.IntegerField(source='supply.stock', read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ['id', 'supply', 'supply_name', 'lot', 'unit_price', 'available_stock', 'quantity', 'subtotal']

    def get_subtotal(self, item):
        return item.supply.unit_price * item.quantity


class CartSerializer(serializers.ModelSerializer):
    """Devuelve las líneas persistidas, el total actual y advertencias de stock."""

    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()
    warnings = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ['id', 'updated_at', 'items', 'total', 'warnings']

    def get_total(self, cart):
        return sum(
            (item.supply.unit_price * item.quantity for item in cart.items.select_related('supply')),
            start=0,
        )

    def get_warnings(self, cart):
        warnings = []
        for item in cart.items.select_related('supply'):
            if item.quantity > item.supply.stock:
                warnings.append({
                    'supply_id': item.supply_id,
                    'supply_name': item.supply.commercial_name,
                    'requested_quantity': item.quantity,
                    'available_stock': item.supply.stock,
                    'message': (
                        f'No hay stock suficiente para {item.supply.commercial_name}. '
                        f'Quedan {item.supply.stock} unidades disponibles.'
                    ),
                })
        return warnings


class PurchaseRequestItemSerializer(serializers.ModelSerializer):
    """Representa una línea histórica con el precio congelado en checkout."""

    class Meta:
        model = PurchaseRequestItem
        fields = ['id', 'supply', 'supply_name', 'lot', 'quantity', 'unit_price', 'subtotal']


class PurchaseRequestSerializer(serializers.ModelSerializer):
    """Serializa solicitudes sin permitir que el cliente altere su historial."""

    institution_name = serializers.CharField(source='institution.name', read_only=True)
    items = PurchaseRequestItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseRequest
        fields = ['id', 'institution', 'institution_name', 'status', 'total', 'created_at', 'updated_at', 'items']
        read_only_fields = fields


class CartItemInputSerializer(serializers.Serializer):
    """Valida altas, incrementos o cambios de cantidad del carro."""

    supply_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, default=1)
    increment = serializers.BooleanField(default=False)


class PurchaseRequestStatusSerializer(serializers.Serializer):
    """Restringe el cambio de estado a los valores definidos en el modelo."""

    status = serializers.ChoiceField(choices=PurchaseRequest.Status.choices)
