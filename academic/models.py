"""Entidades relacionales para el abastecimiento B2B de insumos médicos."""

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.core.validators import MinValueValidator


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


class Material(models.Model):
    """Material o ingrediente base del taller de pastelería para control de inventario y BOM."""

    class Unit(models.TextChoices):
        KILOGRAM = 'kg', 'Kilogramos (kg)'
        GRAM = 'g', 'Gramos (g)'
        LITER = 'L', 'Litros (L)'
        MILLILITER = 'ml', 'Mililitros (ml)'
        UNIT = 'unidades', 'Unidades'
        PACKAGE = 'paquetes', 'Paquetes'

    name = models.CharField(max_length=160, unique=True)
    stock = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    minimum_stock = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=5,
        validators=[MinValueValidator(0)],
    )
    unit = models.CharField(max_length=30, choices=Unit.choices, default=Unit.KILOGRAM)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(stock__gte=0), name='material_stock_nonnegative'),
            models.CheckConstraint(
                condition=Q(minimum_stock__gte=0),
                name='material_min_stock_nonnegative',
            ),
        ]

    @property
    def needs_restock(self):
        return self.stock <= self.minimum_stock

    def __str__(self):
        return self.name


class BakeryOrder(models.Model):
    """Pedido personalizado para producción artesanal y seguimiento interno del proceso."""

    class Status(models.TextChoices):
        RECEIVED = 'recibido', 'Recibido'
        IN_PREPARATION = 'en_preparacion', 'En preparación'
        BAKED = 'horneado', 'Horneado'
        DECORATED = 'decorado', 'Decorado'
        QUALITY_CONTROL = 'control_calidad', 'Control de calidad'
        READY = 'listo', 'Listo'

    customer_name = models.CharField(max_length=180)
    contact_phone = models.CharField(max_length=40, blank=True)
    order_details = models.TextField(blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    delivery_time = models.TimeField(null=True, blank=True)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.RECEIVED)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bakery_orders')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Pedido #{self.pk} - {self.customer_name}'


class BakeryProductOption(models.Model):
    """Opción de torta predefinida o personalizada ofrecida al registrar pedidos."""

    name = models.CharField(max_length=180, unique=True)
    default_price = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    is_customized = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['is_customized', 'name']

    def __str__(self):
        return self.name


class BakeryOrderItem(models.Model):
    """Línea del pedido con descripción del producto final y cantidades requeridas."""

    order = models.ForeignKey(BakeryOrder, on_delete=models.CASCADE, related_name='items')
    product_option = models.ForeignKey(
        BakeryProductOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_items',
    )
    product_name = models.CharField(max_length=180)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f'{self.product_name} x{self.quantity}'


class BOMItem(models.Model):
    """Material requerido para cada pedido, usado para descontar inventario de producción."""

    order = models.ForeignKey(BakeryOrder, on_delete=models.CASCADE, related_name='bom_items')
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name='bom_items')
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f'{self.material.name} - {self.quantity}'
