"""Páginas HTML y API transaccional para la gestión de abastecimiento institucional."""

from collections import defaultdict
from decimal import Decimal
import logging

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import DatabaseError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter

from .filters import MedicalSupplyFilter
from .forms import BakeryOrderForm, BakeryOrderItemFormSet, BOMItemFormSet, MaterialForm
from .models import (
    BakeryOrder,
    BakeryOrderItem,
    BakeryProductOption,
    BOMItem,
    Cart,
    CartItem,
    Material,
    MedicalSupply,
    Profile,
    PurchaseRequest,
    PurchaseRequestItem,
    SupplyCategory,
)
from .permissions import IsMedicalInstitution, IsStaffUser, IsSuperUser, IsWarehouseManager
from .serializers import (
    BakeryOrderSerializer,
    BakeryOrderStatusSerializer,
    BOMItemSerializer,
    CartItemInputSerializer,
    CartSerializer,
    InstitutionRegistrationSerializer,
    MaterialSerializer,
    MedicalSupplySerializer,
    PurchaseRequestSerializer,
    PurchaseRequestStatusSerializer,
    StockRestockSerializer,
    SupplyCategorySerializer,
)

logger = logging.getLogger(__name__)


def home(request):
    """Muestra el panel interno para coordinar pedidos, producción, inventario y despacho."""
    orders = BakeryOrder.objects.prefetch_related('items').order_by('delivery_date', 'delivery_time', '-created_at')
    stages = [
        {
            'title': 'Recibido',
            'statuses': [BakeryOrder.Status.RECEIVED],
        },
        {
            'title': 'En preparación',
            'statuses': [BakeryOrder.Status.IN_PREPARATION],
        },
        {
            'title': 'Horneado / Decorado',
            'statuses': [BakeryOrder.Status.BAKED, BakeryOrder.Status.DECORATED],
        },
        {
            'title': 'Control de calidad',
            'statuses': [BakeryOrder.Status.QUALITY_CONTROL],
        },
        {
            'title': 'Listo',
            'statuses': [BakeryOrder.Status.READY],
        },
    ]
    for stage in stages:
        stage['orders'] = orders.filter(status__in=stage['statuses'])
        stage['count'] = stage['orders'].count()

    materials = Material.objects.filter(is_active=True).order_by('name')
    low_stock_count = sum(1 for material in materials if material.needs_restock)
    ready_orders = orders.filter(status=BakeryOrder.Status.READY)
    context = {
        'stages': stages,
        'materials': materials,
        'low_stock_count': low_stock_count,
        'active_order_count': orders.exclude(status=BakeryOrder.Status.READY).count(),
        'production_order_count': orders.filter(
            status__in=[
                BakeryOrder.Status.IN_PREPARATION,
                BakeryOrder.Status.BAKED,
                BakeryOrder.Status.DECORATED,
                BakeryOrder.Status.QUALITY_CONTROL,
            ]
        ).count(),
        'ready_order_count': ready_orders.count(),
        'ready_orders': ready_orders,
        'today': timezone.localdate(),
    }
    return render(request, 'academic/bakery_home.html', context)


def products_page(request):
    """Redirige la antigua vitrina de farmacia al panel interno de Dulce Arte."""
    return redirect('home')


def cart_page(request):
    """Redirige el antiguo carro de farmacia al panel interno de Dulce Arte."""
    return redirect('home')


def login_page(request):
    """Renderiza el formulario de obtención de tokens JWT."""
    return render(request, 'academic/login.html')


def favicon(request):
    """Entrega un favicon para los navegadores que solicitan /favicon.ico."""
    return HttpResponse(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="6" fill="#174b3f"/>'
        '<path d="M9 16h14M16 9v14" stroke="#d8e8a0" stroke-width="4"/>'
        '</svg>',
        content_type='image/svg+xml',
    )


def register_page(request):
    """Deshabilita el antiguo registro público de clientes de farmacia."""
    return redirect('home')


def warehouse_dashboard_page(request):
    """Entrega el mismo panel operativo de pastelería desde la ruta de administración."""
    return render(request, 'academic/bakery_home.html')


@login_required(login_url='/admin/login/')
@user_passes_test(lambda user: user.is_active and user.is_staff, login_url='/admin/login/')
def inventory_management_page(request):
    """Administra insumos en una página enfocada, sin la navegación general de Django Admin."""
    material_id = request.POST.get('material_id') if request.method == 'POST' else request.GET.get('edit')
    material = get_object_or_404(Material, pk=material_id) if material_id else None
    form = MaterialForm(request.POST or None, instance=material)

    if request.method == 'POST' and form.is_valid():
        saved_material = form.save()
        messages.success(request, f'El insumo «{saved_material.name}» se guardó correctamente.')
        return redirect('inventory-management')

    materials = Material.objects.order_by('name')
    return render(
        request,
        'academic/inventory_management.html',
        {
            'materials': materials,
            'form': form,
            'editing_material': material,
        },
    )


def transition_bakery_order(order_id, target_status):
    """Aplica una transición válida y descuenta la BOM atómicamente al completar producción."""
    with transaction.atomic():
        order = BakeryOrder.objects.select_for_update().get(pk=order_id)
        allowed_transitions = {
            BakeryOrder.Status.RECEIVED: {BakeryOrder.Status.IN_PREPARATION, BakeryOrder.Status.READY},
            BakeryOrder.Status.IN_PREPARATION: {BakeryOrder.Status.BAKED, BakeryOrder.Status.QUALITY_CONTROL},
            BakeryOrder.Status.BAKED: {BakeryOrder.Status.DECORATED, BakeryOrder.Status.QUALITY_CONTROL},
            BakeryOrder.Status.DECORATED: {BakeryOrder.Status.QUALITY_CONTROL},
            BakeryOrder.Status.QUALITY_CONTROL: {BakeryOrder.Status.READY},
            BakeryOrder.Status.READY: set(),
        }
        if target_status not in allowed_transitions.get(order.status, set()):
            raise ValidationError({'status': f'Transición no permitida: {order.status} -> {target_status}.'})

        if target_status == BakeryOrder.Status.READY:
            quantities = defaultdict(lambda: Decimal('0'))
            for bom in order.bom_items.all():
                quantities[bom.material_id] += bom.quantity

            materials = {
                material.pk: material
                for material in Material.objects.select_for_update()
                .filter(pk__in=quantities)
                .order_by('pk')
            }
            for material_id, quantity in quantities.items():
                material = materials[material_id]
                if material.stock < quantity:
                    raise ValidationError({'stock': f'No hay stock suficiente de {material.name}.'})
            for material_id, quantity in quantities.items():
                material = materials[material_id]
                material.stock -= quantity
                material.save(update_fields=['stock'])

        order.status = target_status
        order.save(update_fields=['status', 'updated_at'])
    return order


@login_required(login_url='/admin/login/')
@user_passes_test(lambda user: user.is_active and user.is_staff, login_url='/admin/login/')
def order_management_page(request):
    """Gestiona pedidos y sus productos/BOM en una página separada del Django Admin."""
    order_id = request.POST.get('order_id') if request.method == 'POST' else request.GET.get('edit')
    order = get_object_or_404(BakeryOrder, pk=order_id) if order_id else None

    if request.method == 'POST' and request.POST.get('action') == 'status':
        try:
            updated_order = transition_bakery_order(order.pk, request.POST.get('status'))
        except ValidationError as error:
            messages.error(request, str(error.detail))
        else:
            messages.success(request, f'Pedido #{updated_order.pk} actualizado a «{updated_order.get_status_display()}».')
        return redirect('order-management')

    form = BakeryOrderForm(request.POST or None, instance=order)
    item_formset = BakeryOrderItemFormSet(request.POST or None, instance=order, prefix='items')
    bom_formset = BOMItemFormSet(request.POST or None, instance=order, prefix='bom')
    if request.method == 'POST':
        if form.is_valid() and item_formset.is_valid() and bom_formset.is_valid():
            with transaction.atomic():
                saved_order = form.save(commit=False)
                has_customized_item = any(
                    item_form.cleaned_data.get('product_option')
                    and item_form.cleaned_data['product_option'].is_customized
                    for item_form in item_formset.forms
                    if item_form.cleaned_data and not item_form.cleaned_data.get('DELETE', False)
                )
                if not has_customized_item:
                    saved_order.order_details = ''
                if saved_order.pk is None:
                    saved_order.created_by = request.user
                saved_order.save()
                item_formset.instance = saved_order
                bom_formset.instance = saved_order
                item_formset.save()
                bom_formset.save()
                saved_order.total = sum(
                    (item.unit_price * item.quantity for item in saved_order.items.all()),
                    start=Decimal('0'),
                )
                saved_order.save(update_fields=['total', 'updated_at'])
            messages.success(request, f'El pedido #{saved_order.pk} se guardó correctamente.')
            return redirect('order-management')

    orders = BakeryOrder.objects.prefetch_related('items', 'bom_items__material').order_by(
        'delivery_date', 'delivery_time', '-created_at'
    )
    allowed_transitions = {
        BakeryOrder.Status.RECEIVED: [BakeryOrder.Status.IN_PREPARATION, BakeryOrder.Status.READY],
        BakeryOrder.Status.IN_PREPARATION: [BakeryOrder.Status.BAKED, BakeryOrder.Status.QUALITY_CONTROL],
        BakeryOrder.Status.BAKED: [BakeryOrder.Status.DECORATED, BakeryOrder.Status.QUALITY_CONTROL],
        BakeryOrder.Status.DECORATED: [BakeryOrder.Status.QUALITY_CONTROL],
        BakeryOrder.Status.QUALITY_CONTROL: [BakeryOrder.Status.READY],
        BakeryOrder.Status.READY: [],
    }
    for existing_order in orders:
        next_statuses = allowed_transitions[existing_order.status]
        existing_order.next_status_choices = [
            choice for choice in BakeryOrder.Status.choices if choice[0] in next_statuses
        ]
    return render(
        request,
        'academic/order_management.html',
        {
            'orders': orders,
            'form': form,
            'item_formset': item_formset,
            'bom_formset': bom_formset,
            'editing_order': order,
            'status_choices': BakeryOrder.Status.choices,
            'custom_product_option_id': BakeryProductOption.objects.filter(
                is_customized=True, is_active=True
            ).values_list('pk', flat=True).first(),
            'cake_prices': {
                str(option.pk): str(option.default_price or '')
                for option in BakeryProductOption.objects.filter(is_active=True)
            },
        },
    )


class InstitutionRegistrationView(APIView):
    """Registra una institución médica y su usuario principal en una operación atómica."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=InstitutionRegistrationSerializer, responses={201: None})
    def post(self, request):
        serializer = InstitutionRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {'detail': 'Cuenta institucional creada. Ya puedes iniciar sesión.'},
            status=status.HTTP_201_CREATED,
        )


class DocumentationSessionView(APIView):
    """Crea una sesión Django para que Swagger use la autenticación del administrador."""

    permission_classes = [IsAuthenticated, IsSuperUser]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        login(
            request._request,
            request.user,
            backend='django.contrib.auth.backends.ModelBackend',
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoleAwareWritePermissions:
    """Permite lectura pública y limita la gestión completa del catálogo al superusuario."""

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [AllowAny()]
        return [IsAuthenticated(), IsSuperUser()]


class SupplyCategoryListCreateView(RoleAwareWritePermissions, generics.ListCreateAPIView):
    """Lista categorías públicas y permite gestionarlas solo a usuarios con permisos de bodega."""

    queryset = SupplyCategory.objects.all().order_by('name')
    serializer_class = SupplyCategorySerializer


class SupplyCategoryDetailView(RoleAwareWritePermissions, generics.RetrieveUpdateDestroyAPIView):
    """Expone una categoría y restringe su actualización o eliminación al rol autorizado."""

    queryset = SupplyCategory.objects.all()
    serializer_class = SupplyCategorySerializer


class MedicalSupplyListCreateView(RoleAwareWritePermissions, generics.ListCreateAPIView):
    """Lista insumos con filtros y restringe la creación y edición al gestor de bodega."""

    serializer_class = MedicalSupplySerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MedicalSupplyFilter
    search_fields = ['commercial_name', 'active_ingredient', 'lot', 'category__name']
    ordering_fields = ['commercial_name', 'unit_price', 'stock', 'expiration_date']
    ordering = ['commercial_name', 'expiration_date']

    def get_queryset(self):
        queryset = MedicalSupply.objects.select_related('category')
        if not IsWarehouseManager().has_permission(self.request, self):
            queryset = queryset.filter(is_active=True)
        return queryset


class MedicalSupplyDetailView(RoleAwareWritePermissions, generics.RetrieveUpdateDestroyAPIView):
    """Muestra y administra el detalle de un insumo con validaciones RBAC y filtrado por estado."""

    queryset = MedicalSupply.objects.select_related('category')
    serializer_class = MedicalSupplySerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if not IsWarehouseManager().has_permission(self.request, self):
            queryset = queryset.filter(is_active=True)
        return queryset


class MedicalSupplyRestockView(APIView):
    """Agrega unidades al stock actual sin requerir editar los demás datos del insumo."""

    permission_classes = [IsAuthenticated, IsWarehouseManager]

    @extend_schema(request=StockRestockSerializer, responses=MedicalSupplySerializer)
    def post(self, request, pk):
        serializer = StockRestockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            supply = generics.get_object_or_404(
                MedicalSupply.objects.select_for_update(),
                pk=pk,
            )
            supply.stock += serializer.validated_data['quantity']
            supply.save(update_fields=['stock'])
        return Response(MedicalSupplySerializer(supply).data)


class MedicalCartView(APIView):
    """Lee y modifica el carrito persistente del usuario sin reservar ni descontar inventario."""

    permission_classes = [IsAuthenticated, IsMedicalInstitution]

    @extend_schema(responses=CartSerializer)
    def get(self, request):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart = Cart.objects.prefetch_related('items__supply').get(pk=cart.pk)
        return Response(CartSerializer(cart).data)

    @extend_schema(request=CartItemInputSerializer, responses=CartSerializer)
    def post(self, request):
        input_serializer = CartItemInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            cart, _ = Cart.objects.get_or_create(user=request.user)
            cart = Cart.objects.select_for_update().get(pk=cart.pk)
            supply = generics.get_object_or_404(
                MedicalSupply.objects.select_for_update(),
                pk=input_serializer.validated_data['supply_id'],
                is_active=True,
            )
            item = CartItem.objects.select_for_update().filter(cart=cart, supply=supply).first()
            quantity = input_serializer.validated_data['quantity']
            requested_quantity = (
                item.quantity + quantity
                if item and input_serializer.validated_data['increment']
                else quantity
            )
            if requested_quantity > supply.stock:
                raise ValidationError({
                    'stock': (
                        f'No hay stock suficiente para {supply.commercial_name}. '
                        f'Quedan {supply.stock} unidades disponibles.'
                    )
                })
            if item:
                item.quantity = requested_quantity
                item.save(update_fields=['quantity'])
            else:
                CartItem.objects.create(cart=cart, supply=supply, quantity=quantity)
        cart = Cart.objects.prefetch_related('items__supply').get(pk=cart.pk)
        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)

    @extend_schema(responses={204: None})
    def delete(self, request):
        supply_id = request.query_params.get('supply_id')
        if not supply_id:
            raise ValidationError({'supply_id': 'Este parámetro es obligatorio.'})
        CartItem.objects.filter(cart__user=request.user, supply_id=supply_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PurchaseRequestCheckoutView(APIView):
    """Crea la solicitud del cliente y descuenta el inventario al confirmar la compra."""

    permission_classes = [IsAuthenticated, IsMedicalInstitution]

    @extend_schema(request=None, responses={201: PurchaseRequestSerializer})
    def post(self, request):
        profile = request.user.profile
        if profile.institution_id is None:
            raise ValidationError({'institution': 'Tu cuenta debe estar vinculada a una institución médica.'})

        with transaction.atomic():
            cart = Cart.objects.select_for_update().filter(user=request.user).first()
            if cart is None:
                raise ValidationError({'cart': 'El carro está vacío.'})
            cart_items = list(
                CartItem.objects.select_for_update()
                .filter(cart=cart)
                .select_related('supply')
                .order_by('pk')
            )
            if not cart_items:
                raise ValidationError({'cart': 'El carro está vacío.'})

            # Se valida el stock real del inventario antes de confirmar la solicitud.
            quantities = defaultdict(int)
            for item in cart_items:
                quantities[item.supply_id] += item.quantity

            supplies = {
                supply.pk: supply
                for supply in MedicalSupply.objects.select_for_update()
                .filter(pk__in=quantities)
                .order_by('pk')
            }
            for supply_id, quantity in quantities.items():
                supply = supplies[supply_id]
                if supply.expiration_date < timezone.localdate():
                    raise ValidationError({'stock': f'El lote {supply.lot} está vencido.'})
                if supply.stock < quantity:
                    raise ValidationError({
                        'stock': f'Stock insuficiente para {supply.commercial_name} ({supply.lot}).'
                    })

            for supply_id, quantity in quantities.items():
                supply = supplies[supply_id]
                supply.stock -= quantity
                supply.save(update_fields=['stock'])

            order = PurchaseRequest.objects.create(
                institution=profile.institution,
                created_by=request.user,
            )
            order_items = [
                PurchaseRequestItem(
                    request=order,
                    supply=item.supply,
                    supply_name=item.supply.commercial_name,
                    lot=item.supply.lot,
                    quantity=item.quantity,
                    unit_price=item.supply.unit_price,
                )
                for item in cart_items
            ]
            PurchaseRequestItem.objects.bulk_create(order_items)
            order.total = sum((item.unit_price * item.quantity for item in order_items), start=0)
            order.save(update_fields=['total', 'updated_at'])
            cart.items.all().delete()

        order = PurchaseRequest.objects.prefetch_related('items').select_related('institution').get(pk=order.pk)
        order_data = PurchaseRequestSerializer(order).data
        warnings = []
        for item in order.items.select_related('supply').all():
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
        if warnings:
            order_data['warnings'] = warnings
        return Response(order_data, status=status.HTTP_201_CREATED)


class MyPurchaseRequestsView(generics.ListAPIView):
    """Devuelve el historial de solicitudes de la institución asociada a la cuenta autenticada."""

    permission_classes = [IsAuthenticated, IsMedicalInstitution]
    serializer_class = PurchaseRequestSerializer

    def get_queryset(self):
        return (
            PurchaseRequest.objects.filter(institution_id=self.request.user.profile.institution_id)
            .select_related('institution')
            .prefetch_related('items')
            .order_by('-created_at')
        )


class WarehousePurchaseRequestsView(generics.ListAPIView):
    """Entrega al administrador el listado completo de solicitudes."""

    permission_classes = [IsAuthenticated, IsSuperUser]
    serializer_class = PurchaseRequestSerializer
    queryset = PurchaseRequest.objects.select_related('institution').prefetch_related('items').order_by('-created_at')


class PurchaseRequestStatusView(APIView):
    """Aplica transiciones válidas de estado y sincroniza el inventario en la misma transacción."""

    permission_classes = [IsAuthenticated, IsSuperUser]
    allowed_transitions = {
        PurchaseRequest.Status.PENDING: {
            PurchaseRequest.Status.PAID,
            PurchaseRequest.Status.CANCELLED,
        },
        PurchaseRequest.Status.PAID: {
            PurchaseRequest.Status.DELIVERED,
            PurchaseRequest.Status.CANCELLED,
        },
        PurchaseRequest.Status.DELIVERED: set(),
        PurchaseRequest.Status.CANCELLED: set(),
    }

    @extend_schema(request=PurchaseRequestStatusSerializer, responses=PurchaseRequestSerializer)
    def patch(self, request, pk):
        serializer = PurchaseRequestStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_status = serializer.validated_data['status']

        with transaction.atomic():
            order = generics.get_object_or_404(
                PurchaseRequest.objects.select_for_update(),
                pk=pk,
            )
            current_status = order.status
            if target_status == current_status:
                return Response(PurchaseRequestSerializer(order).data)
            if target_status not in self.allowed_transitions[current_status]:
                raise ValidationError({
                    'status': f'Transición no permitida: {current_status} -> {target_status}.'
                })

            quantities = defaultdict(int)
            for item in order.items.all():
                quantities[item.supply_id] += item.quantity

            if target_status == PurchaseRequest.Status.PAID and current_status == PurchaseRequest.Status.PENDING:
                # El stock ya fue descontado al confirmar la solicitud; el pago solo cambia el estado.
                pass

            if target_status == PurchaseRequest.Status.CANCELLED and current_status in {
                PurchaseRequest.Status.PENDING,
                PurchaseRequest.Status.PAID,
            }:
                # Si la solicitud se cancela, se reingresa al inventario la cantidad que ya había salido.
                supplies = {
                    supply.pk: supply
                    for supply in MedicalSupply.objects.select_for_update()
                    .filter(pk__in=quantities)
                    .order_by('pk')
                }
                for supply_id, quantity in quantities.items():
                    supply = supplies[supply_id]
                    supply.stock += quantity
                    supply.save(update_fields=['stock'])

            order.status = target_status
            order.save(update_fields=['status', 'updated_at'])

        order = PurchaseRequest.objects.select_related('institution').prefetch_related('items').get(pk=order.pk)
        return Response(PurchaseRequestSerializer(order).data)


class MaterialInventoryView(generics.ListCreateAPIView):
    """Inventario base del taller: materiales y commodities para producción artesanal."""

    queryset = Material.objects.filter(is_active=True).order_by('name')
    serializer_class = MaterialSerializer
    permission_classes = [IsAuthenticated, IsSuperUser]


class BakeryOrderListCreateView(generics.ListCreateAPIView):
    """Listado y creación de pedidos personalizados para la pastelería."""

    serializer_class = BakeryOrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff or self.request.user.profile.role == Profile.Role.WAREHOUSE_MANAGER:
            return BakeryOrder.objects.select_related('created_by').prefetch_related('items', 'bom_items__material').order_by('-created_at')
        return BakeryOrder.objects.filter(created_by=self.request.user).select_related('created_by').prefetch_related('items', 'bom_items__material').order_by('-created_at')

    def perform_create(self, serializer):
        order = serializer.save(created_by=self.request.user)
        total = 0
        for item in order.items.all():
            total += item.unit_price * item.quantity
        order.total = total
        order.save(update_fields=['total'])


class BakeryOrderDetailView(generics.RetrieveUpdateAPIView):
    """Detalle de un pedido con trazabilidad de producción y materiales."""

    serializer_class = BakeryOrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff or self.request.user.profile.role == Profile.Role.WAREHOUSE_MANAGER:
            return BakeryOrder.objects.select_related('created_by').prefetch_related('items', 'bom_items__material')
        return BakeryOrder.objects.filter(created_by=self.request.user).select_related('created_by').prefetch_related('items', 'bom_items__material')


class BakeryOrderStatusView(APIView):
    """Mueve un pedido por las etapas del proceso productivo y descuenta inventario en la etapa final."""

    permission_classes = [IsAuthenticated, IsStaffUser]

    @extend_schema(request=BakeryOrderStatusSerializer, responses=BakeryOrderSerializer)
    def patch(self, request, pk):
        serializer = BakeryOrderStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_status = serializer.validated_data['status']
        order = transition_bakery_order(pk, target_status)

        return Response(BakeryOrderSerializer(BakeryOrder.objects.prefetch_related('items', 'bom_items__material').get(pk=order.pk)).data)


def error_404(request, exception):
    """Renderiza la vista de error para rutas web inexistentes del storefront."""
    return render(request, '404.html', status=404)
