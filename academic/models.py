"""Entidades relacionales para el abastecimiento B2B de insumos médicos."""

from django.contrib.auth.models import User
from django.db import models


class Institution(models.Model):
    """Institución médica que compra insumos a la farmacia B2B."""

    name = models.CharField(max_length=180, unique=True)
    tax_id = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.name


class Profile(models.Model):
    """Rol e institución asociados a una cuenta autenticada para el flujo de compras y bodega."""

    class Role(models.TextChoices):
        MEDICAL_INSTITUTION = 'institucion_medica', 'Institución médica'
        WAREHOUSE_MANAGER = 'gestor_bodega', 'Gestor de bodega'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.MEDICAL_INSTITUTION)
    birth_date = models.DateField(null=True, blank=True)
    institution = models.ForeignKey(
        Institution,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='profiles',
    )

    def __str__(self):
        return f'{self.user.username} ({self.get_role_display()})'


class SupplyCategory(models.Model):
    """Categoría de inventario, por ejemplo medicamentos o material quirúrgico."""

    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class MedicalSupply(models.Model):
    """Insumo comercializado por lote, con vencimiento y stock de cajas."""

    category = models.ForeignKey(SupplyCategory, on_delete=models.PROTECT, related_name='supplies')
    commercial_name = models.CharField(max_length=180)
    active_ingredient = models.CharField(max_length=180, blank=True)
    lot = models.CharField(max_length=80)
    expiration_date = models.DateField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    image_url = models.URLField(blank=True)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['lot', 'commercial_name'], name='unique_supply_lot_name'),
        ]
        ordering = ['commercial_name', 'expiration_date']

    def __str__(self):
        return f'{self.commercial_name} ({self.lot})'


class Cart(models.Model):
    """Carrito persistente del usuario, independiente de la sesión del navegador."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='medical_cart')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Carro de {self.user.username}'


class CartItem(models.Model):
    """Cantidad de un insumo dentro del carrito; no reserva inventario hasta confirmar la solicitud."""

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    supply = models.ForeignKey(MedicalSupply, on_delete=models.PROTECT, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cart', 'supply'], name='unique_supply_per_cart'),
        ]


class PurchaseRequest(models.Model):
    """Solicitud histórica con estados explícitos para el flujo de compra y control de inventario."""

    class Status(models.TextChoices):
        PENDING = 'pendiente', 'Pendiente'
        PAID = 'pagado', 'Pagado'
        DELIVERED = 'entregado', 'Entregado'
        CANCELLED = 'cancelado', 'Cancelado'

    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name='requests')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='purchase_requests')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PurchaseRequestItem(models.Model):
    """Detalle que conserva nombre, lote y precio vigentes al confirmar la compra."""

    request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name='items')
    supply = models.ForeignKey(MedicalSupply, on_delete=models.PROTECT, related_name='request_items')
    supply_name = models.CharField(max_length=180)
    lot = models.CharField(max_length=80)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def subtotal(self):
        return self.unit_price * self.quantity
