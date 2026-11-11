"""Pruebas de integración del abastecimiento institucional."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.db import IntegrityError, OperationalError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from .forms import BakeryOrderForm
from .models import (
    BakeryOrder,
    BakeryProductOption,
    BOMItem,
    Institution,
    Material,
    MedicalSupply,
    Profile,
    PurchaseRequest,
    SupplyCategory,
)


class PharmacyApiTests(TestCase):
    """Cubre autenticación, catálogo, carrito, confirmación de compra y descuento de stock."""

    def setUp(self):
        self.institution = Institution.objects.create(name='Centro Médico de Prueba')
        self.category = SupplyCategory.objects.create(name='Medicamentos')
        self.supply = MedicalSupply.objects.create(
            category=self.category,
            commercial_name='Paracetamol 500 mg',
            active_ingredient='Paracetamol',
            lot='LOT-2026-01',
            expiration_date=date(2028, 12, 31),
            unit_price=Decimal('2500.00'),
            stock=5,
        )
        user_model = get_user_model()
        self.customer = user_model.objects.create_user(username='institucion', password='secret123')
        Profile.objects.create(
            user=self.customer,
            role=Profile.Role.MEDICAL_INSTITUTION,
            institution=self.institution,
        )
        self.manager = user_model.objects.create_user(
            username='gestor',
            password='secret123',
            is_staff=True,
        )
        Profile.objects.create(user=self.manager, role=Profile.Role.WAREHOUSE_MANAGER)
        self.admin = user_model.objects.create_superuser(
            username='admin',
            email='admin@example.test',
            password='secret123',
        )

    def authenticate(self, user):
        response = self.client.post(
            '/api/token/',
            {'username': user.username, 'password': 'secret123'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.client.defaults['HTTP_AUTHORIZATION'] = f"Bearer {response.json()['access']}"
        return AccessToken(response.json()['access'])

    def test_public_catalog_filters_and_documentation(self):
        response = self.client.get(
            f'/api/insumos/?category={self.category.pk}&price_min=2000&price_max=3000'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]['commercial_name'], 'Paracetamol 500 mg')
        self.assertEqual(self.client.get('/api/categorias/').status_code, 200)
        self.assertEqual(self.client.get('/api/docs/').status_code, 401)

        self.authenticate(self.manager)
        self.assertEqual(self.client.get('/api/docs/').status_code, 403)
        self.assertEqual(self.client.get('/api/schema/').status_code, 403)

    def test_jwt_contains_role_claim_and_catalog_writes_are_restricted(self):
        token = self.authenticate(self.customer)

        self.assertEqual(token['role'], Profile.Role.MEDICAL_INSTITUTION)
        response = self.client.post(
            '/api/insumos/',
            {'category': self.category.pk, 'commercial_name': 'Gasa', 'lot': 'G-1',
             'expiration_date': '2028-12-31', 'unit_price': '1000.00', 'stock': 10},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_user_gets_manager_role_even_if_profile_was_created_as_customer(self):
        self.manager.profile.role = Profile.Role.MEDICAL_INSTITUTION
        self.manager.profile.save(update_fields=['role'])

        token = self.authenticate(self.manager)

        self.assertEqual(token['role'], Profile.Role.WAREHOUSE_MANAGER)
        self.manager.profile.refresh_from_db()
        self.assertEqual(self.manager.profile.role, Profile.Role.WAREHOUSE_MANAGER)

    def test_cart_persists_and_checkout_reduces_stock_in_database(self):
        """La confirmación de la solicitud debe descontar el stock en la base de datos."""
        self.authenticate(self.customer)
        add_response = self.client.post(
            '/api/carro-insumos/',
            {'supply_id': self.supply.pk, 'quantity': 2},
            content_type='application/json',
        )
        self.assertEqual(add_response.status_code, 200)
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 5)

        self.client.defaults.pop('HTTP_AUTHORIZATION')
        self.authenticate(self.customer)
        cart_response = self.client.get('/api/carro-insumos/')
        self.assertEqual(cart_response.json()['items'][0]['quantity'], 2)

        response = self.client.post('/api/solicitudes/confirmar/')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['status'], PurchaseRequest.Status.PENDING)
        self.assertEqual(response.json()['total'], '5000.00')

        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 3)

    def test_adding_same_supply_increments_one_cart_line(self):
        self.authenticate(self.customer)
        endpoint = '/api/carro-insumos/'
        self.client.post(
            endpoint,
            {'supply_id': self.supply.pk, 'quantity': 1, 'increment': True},
            content_type='application/json',
        )
        response = self.client.post(
            endpoint,
            {'supply_id': self.supply.pk, 'quantity': 2, 'increment': True},
            content_type='application/json',
        )

        self.assertEqual(len(response.json()['items']), 1)
        self.assertEqual(response.json()['items'][0]['quantity'], 3)

    def test_cart_rejects_adding_more_than_available_stock(self):
        self.authenticate(self.customer)
        endpoint = '/api/carro-insumos/'
        first_response = self.client.post(
            endpoint,
            {'supply_id': self.supply.pk, 'quantity': 1},
            content_type='application/json',
        )
        self.assertEqual(first_response.status_code, 200)

        self.supply.stock = 1
        self.supply.save(update_fields=['stock'])
        response = self.client.post(
            endpoint,
            {'supply_id': self.supply.pk, 'quantity': 1, 'increment': True},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('No hay stock suficiente', response.json()['stock'])
        cart_response = self.client.get(endpoint)
        self.assertEqual(cart_response.json()['items'][0]['quantity'], 1)

    def test_pending_order_keeps_stock_reduced_and_paid_state_does_not_double_deduct(self):
        """La solicitud pendiente ya descontó stock; el pago solo cambia el estado."""
        self.authenticate(self.customer)
        self.client.post(
            '/api/carro-insumos/',
            {'supply_id': self.supply.pk, 'quantity': 2},
            content_type='application/json',
        )
        order = self.client.post('/api/solicitudes/confirmar/').json()
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 3)

        self.authenticate(self.admin)
        paid = self.client.patch(
            f"/api/solicitudes/{order['id']}/estado/",
            {'status': PurchaseRequest.Status.PAID},
            content_type='application/json',
        )
        self.assertEqual(paid.status_code, 200)
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 3)

        cancelled = self.client.patch(
            f"/api/solicitudes/{order['id']}/estado/",
            {'status': PurchaseRequest.Status.CANCELLED},
            content_type='application/json',
        )
        self.assertEqual(cancelled.status_code, 200)
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 5)

    def test_checkout_is_rejected_when_stock_is_insufficient(self):
        """Se rechaza la compra si el inventario disponible no cubre la cantidad solicitada."""
        self.authenticate(self.customer)
        self.client.post(
            '/api/carro-insumos/',
            {'supply_id': self.supply.pk, 'quantity': 6},
            content_type='application/json',
        )

        response = self.client.post('/api/solicitudes/confirmar/')

        self.assertEqual(response.status_code, 400)
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 5)

    def test_html_pages_show_student_footer(self):
        for path in ['/', '/login/', '/gestor/']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Completar nombre del estudiante')

    def test_legacy_customer_pages_redirect_to_internal_operations_panel(self):
        for path in ['/products/', '/cart/', '/register/']:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertRedirects(response, '/')

    def test_favicon_is_served(self):
        response = self.client.get('/favicon.ico')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/svg+xml')

    def test_admin_login_uses_the_site_theme_without_static_assets(self):
        response = self.client.get('/admin/login/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DULCE ARTE')
        self.assertContains(response, 'color-scheme: light')
        self.assertContains(response, 'href="/"')

    def test_account_and_cart_storage_is_scoped_to_each_tab(self):
        for path in ['/login/', '/gestor/']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'sessionStorage')
            self.assertNotContains(response, "localStorage.getItem('nexo-access-token')")

    def test_warehouse_manager_can_open_warehouse_dashboard(self):
        self.client.force_login(self.manager)
        response = self.client.get('/gestor/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Panel del taller')

    def test_dashboard_shows_only_materials_and_orders_from_database(self):
        empty_dashboard = self.client.get('/')

        self.assertEqual(empty_dashboard.status_code, 200)
        self.assertContains(empty_dashboard, 'Inventario aún no configurado')
        self.assertContains(empty_dashboard, 'No hay pedidos listos para despacho')
        self.assertNotContains(empty_dashboard, 'Chocolate cobertura')
        self.assertNotContains(empty_dashboard, '#DA-104')

        material = Material.objects.create(
            name='Harina de prueba',
            stock=2,
            minimum_stock=5,
            unit='kg',
        )
        order = BakeryOrder.objects.create(
            customer_name='Cliente de prueba',
            order_details='Torta de cumpleaños',
            delivery_date=date(2026, 11, 12),
            status=BakeryOrder.Status.RECEIVED,
        )
        dashboard = self.client.get('/')

        self.assertContains(dashboard, material.name)
        self.assertContains(dashboard, '2 kg')
        self.assertContains(dashboard, 'Solicitar reposición')
        self.assertContains(dashboard, f'#DA-{order.pk}')
        self.assertContains(dashboard, order.customer_name)
        self.assertNotContains(dashboard, 'Chocolate cobertura')

    def test_dashboard_limits_the_inventory_preview_to_five_materials(self):
        for index in range(1, 7):
            Material.objects.create(name=f'Ingrediente {index:02}', stock=index, minimum_stock=0)

        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mostrando 5 de 6 insumos')
        self.assertContains(response, 'Ingrediente 05')
        self.assertEqual(response.content.count(b'class="stock-row"'), 5)
        self.assertContains(response, 'Ver inventario completo')

    def test_material_stock_and_minimum_cannot_be_negative(self):
        material = Material(
            name='Stock inválido',
            stock=Decimal('-1'),
            minimum_stock=Decimal('0'),
        )
        with self.assertRaises(DjangoValidationError):
            material.full_clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Material.objects.create(
                    name='Stock negativo en base',
                    stock=Decimal('-1'),
                    minimum_stock=Decimal('0'),
                )

    def test_bom_deduction_aggregates_duplicate_lines_before_decrement(self):
        material = Material.objects.create(name='Harina', stock=3, minimum_stock=1)
        order = BakeryOrder.objects.create(
            customer_name='Cliente BOM',
            status=BakeryOrder.Status.QUALITY_CONTROL,
        )
        BOMItem.objects.create(order=order, material=material, quantity=Decimal('2'))
        BOMItem.objects.create(order=order, material=material, quantity=Decimal('2'))
        self.authenticate(self.admin)

        response = self.client.patch(
            f'/api/pedidos/{order.pk}/estado/',
            {'status': BakeryOrder.Status.READY},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        material.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(material.stock, Decimal('3.00'))
        self.assertEqual(order.status, BakeryOrder.Status.QUALITY_CONTROL)

    def test_bom_stock_is_deducted_when_production_order_becomes_ready(self):
        material = Material.objects.create(name='Azúcar', stock=8, minimum_stock=1)
        order = BakeryOrder.objects.create(
            customer_name='Cliente pedido listo',
            status=BakeryOrder.Status.QUALITY_CONTROL,
        )
        BOMItem.objects.create(order=order, material=material, quantity=Decimal('2'))
        self.authenticate(self.admin)

        response = self.client.patch(
            f'/api/pedidos/{order.pk}/estado/',
            {'status': BakeryOrder.Status.READY},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], BakeryOrder.Status.READY)
        material.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(material.stock, Decimal('6.00'))
        self.assertEqual(order.status, BakeryOrder.Status.READY)

    def test_dashboard_links_open_focused_inventory_and_order_pages(self):
        self.client.force_login(self.admin)
        dashboard = self.client.get('/')

        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, '/inventario/')
        self.assertContains(dashboard, '/pedidos/')
        self.assertEqual(self.client.get('/inventario/').status_code, 200)
        self.assertEqual(self.client.get('/pedidos/').status_code, 200)

    def test_order_management_is_not_registered_in_django_admin(self):
        self.client.force_login(self.admin)
        admin_index = self.client.get('/admin/')

        self.assertEqual(admin_index.status_code, 200)
        self.assertNotContains(admin_index, 'Pedidos de pastelería')
        self.assertEqual(self.client.get('/admin/academic/bakeryorder/').status_code, 404)
        self.assertEqual(self.client.get('/admin/academic/bakeryorderitem/').status_code, 404)
        self.assertEqual(self.client.get('/admin/academic/bomitem/').status_code, 404)

    def test_delivery_date_cannot_be_in_the_past_and_date_picker_starts_today(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        today_form = BakeryOrderForm({
            'customer_name': 'Cliente fecha de hoy',
            'delivery_date': today.isoformat(),
        })
        past_form = BakeryOrderForm({
            'customer_name': 'Cliente fecha pasada',
            'delivery_date': yesterday.isoformat(),
        })

        self.assertTrue(today_form.is_valid(), today_form.errors)
        self.assertFalse(past_form.is_valid())
        self.assertIn('La fecha de entrega no puede ser anterior a hoy.', past_form.errors['delivery_date'])
        self.assertEqual(
            today_form.fields['delivery_date'].widget.attrs['min'],
            today.isoformat(),
        )

    def test_order_management_requires_staff_and_saves_order_items_and_bom(self):
        call_command('seed_bakery_products', verbosity=0)
        material = Material.objects.create(name='Harina', stock=8, minimum_stock=2, unit='kg')
        self.assertEqual(self.client.get('/pedidos/').status_code, 302)

        self.client.force_login(self.customer)
        self.assertEqual(self.client.get('/pedidos/').status_code, 302)

        self.client.force_login(self.manager)
        page = self.client.get('/pedidos/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Administrar pedidos')
        self.assertNotContains(page, 'id="nav-sidebar"')

        response = self.client.post(
            '/pedidos/',
            {
                'customer_name': 'Cliente pedido prueba',
                'contact_phone': '555123',
                'order_details': 'Torta de cumpleaños',
                'delivery_date': '2026-11-20',
                'delivery_time': '15:30',
                'items-TOTAL_FORMS': '1',
                'items-INITIAL_FORMS': '0',
                'items-MIN_NUM_FORMS': '0',
                'items-MAX_NUM_FORMS': '1000',
                'items-0-product_option': str(BakeryProductOption.objects.get(name='Torta de chocolate').pk),
                'items-0-product_name': '',
                'items-0-quantity': '2',
                'items-0-unit_price': '15000',
                'items-0-notes': '',
                'items-0-DELETE': '',
                'bom-TOTAL_FORMS': '1',
                'bom-INITIAL_FORMS': '0',
                'bom-MIN_NUM_FORMS': '0',
                'bom-MAX_NUM_FORMS': '1000',
                'bom-0-material': str(material.pk),
                'bom-0-quantity': '1.5',
                'bom-0-notes': '',
                'bom-0-DELETE': '',
            },
        )
        self.assertRedirects(response, '/pedidos/')
        order = BakeryOrder.objects.get(customer_name='Cliente pedido prueba')
        self.assertEqual(order.total, Decimal('30000.00'))
        self.assertEqual(order.items.get().product_name, 'Torta de chocolate')
        self.assertEqual(order.items.get().product_option.name, 'Torta de chocolate')
        self.assertEqual(order.order_details, '')
        self.assertEqual(order.bom_items.get().material, material)
        self.assertEqual(order.created_by, self.manager)

    def test_custom_cake_selection_saves_custom_details_and_order_description(self):
        call_command('seed_bakery_products', verbosity=0)
        custom_option = BakeryProductOption.objects.get(is_customized=True)
        self.client.force_login(self.manager)

        response = self.client.post(
            '/pedidos/',
            {
                'customer_name': 'Cliente torta personalizada',
                'contact_phone': '',
                'order_details': 'Diseño de dos pisos con flores azules',
                'delivery_date': '',
                'delivery_time': '',
                'items-TOTAL_FORMS': '1',
                'items-INITIAL_FORMS': '0',
                'items-MIN_NUM_FORMS': '0',
                'items-MAX_NUM_FORMS': '1000',
                'items-0-product_option': str(custom_option.pk),
                'items-0-product_name': 'Torta de cumpleaños',
                'items-0-quantity': '1',
                'items-0-unit_price': '25000',
                'items-0-notes': 'Bizcocho de vainilla, relleno de frutilla',
                'items-0-DELETE': '',
                'bom-TOTAL_FORMS': '0',
                'bom-INITIAL_FORMS': '0',
                'bom-MIN_NUM_FORMS': '0',
                'bom-MAX_NUM_FORMS': '1000',
            },
        )

        self.assertRedirects(response, '/pedidos/')
        order = BakeryOrder.objects.get(customer_name='Cliente torta personalizada')
        item = order.items.get()
        self.assertEqual(item.product_option, custom_option)
        self.assertEqual(item.product_name, 'Torta de cumpleaños')
        self.assertEqual(item.notes, 'Bizcocho de vainilla, relleno de frutilla')
        self.assertEqual(order.order_details, 'Diseño de dos pisos con flores azules')

    def test_cake_product_seed_adds_ten_common_options_and_custom_option_idempotently(self):
        call_command('seed_bakery_products', verbosity=0)
        self.assertEqual(BakeryProductOption.objects.filter(is_customized=False).count(), 10)
        self.assertEqual(BakeryProductOption.objects.filter(is_customized=True).count(), 1)
        chocolate = BakeryProductOption.objects.get(name='Torta de chocolate')
        customized = BakeryProductOption.objects.get(is_customized=True)
        self.assertEqual(chocolate.default_price, Decimal('14990'))
        self.assertIsNone(customized.default_price)

        chocolate.default_price = Decimal('12000')
        chocolate.save(update_fields=['default_price'])

        call_command('seed_bakery_products', verbosity=0)

        self.assertEqual(BakeryProductOption.objects.count(), 11)
        chocolate.refresh_from_db()
        self.assertEqual(chocolate.default_price, Decimal('12000'))

    def test_order_form_shows_ten_common_cakes_and_hides_custom_fields_initially(self):
        call_command('seed_bakery_products', verbosity=0)
        self.client.force_login(self.manager)

        response = self.client.get('/pedidos/')

        self.assertEqual(response.status_code, 200)
        for cake_name in BakeryProductOption.objects.filter(is_customized=False).values_list('name', flat=True):
            self.assertContains(response, cake_name)
        chocolate = BakeryProductOption.objects.get(name='Torta de chocolate')
        self.assertEqual(response.context['cake_prices'][str(chocolate.pk)], '14990')
        self.assertContains(response, 'Torta personalizada')
        self.assertContains(response, 'Precio unitario (CLP, editable)')
        self.assertContains(response, 'Puedes editarlo', html=False)
        self.assertContains(response, 'id="order-description-section" hidden')
        self.assertContains(response, 'data-custom-fields hidden')

    def test_inventory_management_page_requires_staff_and_can_edit_stock(self):
        material = Material.objects.create(
            name='Harina',
            stock=2,
            minimum_stock=5,
            unit='kg',
        )
        self.assertEqual(self.client.get('/inventario/').status_code, 302)

        self.client.force_login(self.customer)
        self.assertEqual(self.client.get('/inventario/').status_code, 302)

        self.client.force_login(self.admin)
        response = self.client.get('/inventario/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Inventario de insumos')
        self.assertContains(response, 'Harina')
        self.assertNotContains(response, 'id="nav-sidebar"')

        response = self.client.post(
            '/inventario/',
            {
                'material_id': material.pk,
                'name': 'Harina',
                'stock': '12.5',
                'minimum_stock': '5',
                'unit': 'kg',
                'is_active': 'on',
            },
        )
        self.assertRedirects(response, '/inventario/')
        material.refresh_from_db()
        self.assertEqual(material.stock, Decimal('12.50'))

        response = self.client.post(
            '/inventario/',
            {
                'material_id': material.pk,
                'name': 'Harina',
                'stock': '-1',
                'minimum_stock': '5',
                'unit': 'kg',
                'is_active': 'on',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('stock', response.context['form'].errors)
        material.refresh_from_db()
        self.assertEqual(material.stock, Decimal('12.50'))

    def test_only_superuser_can_open_documentation_session(self):
        self.authenticate(self.customer)
        denied = self.client.post('/api/docs/session/')
        self.assertEqual(denied.status_code, 403)

        self.client.defaults.pop('HTTP_AUTHORIZATION')
        self.authenticate(self.manager)
        response = self.client.post('/api/docs/session/')

        self.assertEqual(response.status_code, 403)
        self.client.defaults.pop('HTTP_AUTHORIZATION')
        self.assertEqual(self.client.get('/api/docs/').status_code, 401)
        self.assertEqual(self.client.get('/api/schema/').status_code, 401)

    def test_warehouse_manager_cannot_open_django_admin(self):
        self.client.force_login(self.manager)

        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 302)

    def test_warehouse_manager_cannot_open_admin_user_management(self):
        self.client.force_login(self.manager)
        add_page = self.client.get('/admin/auth/user/add/')

        self.assertEqual(add_page.status_code, 302)

    def test_only_superuser_can_open_staff_user_creation_template(self):
        self.client.force_login(self.manager)
        response = self.client.get('/usuarios/nuevo/')
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        response = self.client.get('/usuarios/nuevo/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Agregar administrador')

    def test_superuser_can_create_staff_user_without_django_admin_access(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            '/usuarios/nuevo/',
            {
                'username': 'nuevo_gestor',
                'first_name': 'Nuevo',
                'last_name': 'Gestor',
                'email': 'gestor@example.test',
                'password1': 'UnaClaveSegura-2026',
                'password2': 'UnaClaveSegura-2026',
                'is_superuser': 'on',
            },
        )

        self.assertRedirects(response, '/usuarios/nuevo/')
        user = get_user_model().objects.get(username='nuevo_gestor')
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password('UnaClaveSegura-2026'))
        self.assertEqual(user.profile.role, Profile.Role.WAREHOUSE_MANAGER)

        self.client.force_login(user)
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_staff_can_advance_order_stage_without_django_admin(self):
        order = BakeryOrder.objects.create(
            customer_name='Cliente etapa staff',
            status=BakeryOrder.Status.RECEIVED,
        )
        self.client.force_login(self.manager)

        page = self.client.get('/pedidos/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Avanzar')

        response = self.client.post(
            '/pedidos/',
            {'action': 'status', 'order_id': order.pk, 'status': BakeryOrder.Status.IN_PREPARATION},
        )

        self.assertRedirects(response, '/pedidos/')
        order.refresh_from_db()
        self.assertEqual(order.status, BakeryOrder.Status.IN_PREPARATION)
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_inventory_page_provides_a_stock_management_action(self):
        self.client.force_login(self.admin)
        response = self.client.get('/inventario/')

        self.assertContains(response, 'Agregar insumo')
        self.assertContains(response, 'Existencias registradas')
        self.assertContains(response, '<select name="unit"', html=False)
        self.assertContains(response, 'Kilogramos (kg)')
        self.assertContains(response, 'Unidades')

    def test_inventory_page_rejects_units_outside_the_choices(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            '/inventario/',
            {
                'name': 'Unidad inválida',
                'stock': '1',
                'minimum_stock': '0',
                'unit': 'tazas',
                'is_active': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('unit', response.context['form'].errors)
        self.assertFalse(Material.objects.filter(name='Unidad inválida').exists())

    def test_material_management_is_not_registered_in_django_admin(self):
        self.client.force_login(self.admin)

        admin_index = self.client.get('/admin/')
        self.assertEqual(admin_index.status_code, 200)
        self.assertNotContains(admin_index, 'Materiales')
        self.assertNotContains(admin_index, '/admin/academic/material/')
        self.assertEqual(self.client.get('/admin/academic/material/').status_code, 404)

    def test_seed_bakery_materials_is_idempotent_and_does_not_overwrite_stock(self):
        call_command('seed_bakery_materials', verbosity=0)
        flour = Material.objects.get(name='Harina de trigo')
        self.assertEqual(flour.stock, Decimal('0.00'))
        self.assertEqual(flour.unit, 'kg')

        flour.stock = Decimal('12.5')
        flour.save(update_fields=['stock'])
        initial_count = Material.objects.count()

        call_command('seed_bakery_materials', verbosity=0)

        self.assertEqual(Material.objects.count(), initial_count)
        flour.refresh_from_db()
        self.assertEqual(flour.stock, Decimal('12.5'))

    def test_warehouse_manager_cannot_create_or_edit_catalog_items(self):
        self.authenticate(self.manager)
        payload = {
            'category': self.category.pk,
            'commercial_name': 'Gasas estériles',
            'active_ingredient': '',
            'lot': 'LOT-GASA-01',
            'expiration_date': '2028-12-31',
            'unit_price': '1200.00',
            'stock': 25,
            'image_url': '',
            'is_active': True,
        }
        created = self.client.post('/api/insumos/', payload, content_type='application/json')

        self.assertEqual(created.status_code, 403)
        updated = self.client.patch(
            f'/api/insumos/{self.supply.pk}/',
            {'stock': 30, 'is_active': False},
            content_type='application/json',
        )

        self.assertEqual(updated.status_code, 403)
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 5)
        self.assertTrue(self.supply.is_active)

    def test_warehouse_manager_cannot_view_or_change_purchase_requests(self):
        self.authenticate(self.manager)
        self.assertEqual(self.client.get('/api/solicitudes/').status_code, 403)
        self.assertEqual(
            self.client.patch(
                '/api/solicitudes/1/estado/',
                {'status': PurchaseRequest.Status.PAID},
                content_type='application/json',
            ).status_code,
            403,
        )

    def test_warehouse_manager_can_add_stock_without_overwriting_current_stock(self):
        self.authenticate(self.manager)
        response = self.client.post(
            f'/api/insumos/{self.supply.pk}/agregar-stock/',
            {'quantity': 7},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['stock'], 12)
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 12)

    def test_customer_cannot_add_stock(self):
        self.authenticate(self.customer)
        response = self.client.post(
            f'/api/insumos/{self.supply.pk}/agregar-stock/',
            {'quantity': 7},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 5)

    def test_cart_rejects_checkout_when_stock_is_insufficient(self):
        """El checkout debe fallar si la disponibilidad del stock es insuficiente."""
        self.authenticate(self.customer)
        self.client.post(
            '/api/carro-insumos/',
            {'supply_id': self.supply.pk, 'quantity': 2},
            content_type='application/json',
        )

        self.supply.stock = 0
        self.supply.save(update_fields=['stock'])

        response = self.client.get('/api/carro-insumos/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('warnings', response.json())
        self.assertTrue(any(item['supply_id'] == self.supply.pk for item in response.json()['warnings']))

        checkout_response = self.client.post('/api/solicitudes/confirmar/')
        self.assertEqual(checkout_response.status_code, 400)
        self.assertIn('Stock insuficiente', checkout_response.json()['stock'])
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 0)

        self.authenticate(self.manager)
        restock_response = self.client.post(
            f'/api/insumos/{self.supply.pk}/agregar-stock/',
            {'quantity': 3},
            content_type='application/json',
        )
        self.assertEqual(restock_response.status_code, 200)

        self.authenticate(self.customer)
        checkout_response = self.client.post('/api/solicitudes/confirmar/')
        self.assertEqual(checkout_response.status_code, 201)
        self.supply.refresh_from_db()
        self.assertEqual(self.supply.stock, 1)

    def test_homepage_is_internal_dashboard_and_customer_catalog_redirects(self):
        home_response = self.client.get('/')
        catalog_response = self.client.get('/products/')

        self.assertContains(home_response, 'Panel del taller')
        self.assertRedirects(catalog_response, '/')

    @patch('academic.views.SupplyCategory.objects.annotate', side_effect=OperationalError('database unavailable'))
    def test_homepage_still_renders_when_legacy_catalog_database_fails(self, _annotate):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Inventario aún no configurado')

    def test_public_registration_creates_customer_profile_not_manager(self):
        response = self.client.post(
            '/api/registro/',
            {
                'institution_name': 'Clínica Nueva',
                'tax_id': '761234567',
                'birth_date': '1990-05-12',
                'username': 'clinica_nueva',
                'email': 'contacto@clinica.example',
                'password': 'clave-segura-123',
                'password_confirm': 'clave-segura-123',
                'role': Profile.Role.WAREHOUSE_MANAGER,
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        user = get_user_model().objects.get(username='clinica_nueva')
        self.assertTrue(user.check_password('clave-segura-123'))
        self.assertEqual(user.profile.role, Profile.Role.MEDICAL_INSTITUTION)
        self.assertEqual(user.profile.institution.name, 'Clínica Nueva')
        self.assertEqual(user.profile.birth_date.isoformat(), '1990-05-12')
        self.assertEqual(user.profile.institution.tax_id, '76.123.456-7')

    def test_public_registration_without_institution_name_uses_tax_id(self):
        registration_data = {
            'tax_id': '76.123.456-7',
            'email': 'contacto@clinica.example',
            'password': 'clave-segura-123',
            'password_confirm': 'clave-segura-123',
        }
        first_response = self.client.post(
            '/api/registro/',
            {'username': 'clinica_uno', **registration_data},
            content_type='application/json',
        )
        second_response = self.client.post(
            '/api/registro/',
            {
                **registration_data,
                'username': 'clinica_dos',
                'email': 'contacto2@clinica.example',
            },
            content_type='application/json',
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)
        first_user = get_user_model().objects.get(username='clinica_uno')
        second_user = get_user_model().objects.get(username='clinica_dos')
        self.assertEqual(first_user.profile.institution, second_user.profile.institution)

    def test_registration_rejects_mismatched_passwords(self):
        response = self.client.post(
            '/api/registro/',
            {
                'institution_name': 'Clínica Registro',
                'username': 'registro',
                'email': 'registro@clinica.example',
                'password': 'clave-segura-123',
                'password_confirm': 'otra-clave-123',
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(get_user_model().objects.filter(username='registro').exists())

    def test_registration_rejects_future_birth_date(self):
        response = self.client.post(
            '/api/registro/',
            {
                'birth_date': (timezone.localdate() + timedelta(days=1)).isoformat(),
                'username': 'fecha_futura',
                'email': 'fecha_futura@clinica.example',
                'password': 'clave-segura-123',
                'password_confirm': 'clave-segura-123',
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('birth_date', response.json())
        self.assertFalse(get_user_model().objects.filter(username='fecha_futura').exists())

    def test_registration_rejects_tax_id_with_more_than_eight_body_digits(self):
        response = self.client.post(
            '/api/registro/',
            {
                'tax_id': '13.257.874.324-67',
                'username': 'rut_largo',
                'email': 'rut_largo@clinica.example',
                'password': 'clave-segura-123',
                'password_confirm': 'clave-segura-123',
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('tax_id', response.json())
        self.assertFalse(get_user_model().objects.filter(username='rut_largo').exists())
