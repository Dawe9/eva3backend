"""Pruebas de integración del abastecimiento institucional."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import TestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from .models import Institution, MedicalSupply, Profile, PurchaseRequest, SupplyCategory


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
        for path in ['/', '/products/', '/cart/', '/login/', '/register/', '/gestor/']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Completar nombre del estudiante')

    def test_favicon_is_served(self):
        response = self.client.get('/favicon.ico')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/svg+xml')

    def test_admin_login_uses_the_site_theme_without_static_assets(self):
        response = self.client.get('/admin/login/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BOTICA')
        self.assertContains(response, 'color-scheme: light')
        self.assertContains(response, 'href="/"')

    def test_account_and_cart_storage_is_scoped_to_each_tab(self):
        for path in ['/login/', '/products/', '/cart/', '/gestor/']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'sessionStorage')
            self.assertNotContains(response, "localStorage.getItem('nexo-access-token')")

    def test_warehouse_manager_can_open_warehouse_dashboard(self):
        self.client.force_login(self.manager)
        response = self.client.get('/gestor/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Panel de administración')

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

    def test_warehouse_manager_can_open_django_admin(self):
        self.client.force_login(self.manager)

        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Administración')

    def test_warehouse_manager_can_open_admin_user_management(self):
        self.client.force_login(self.manager)
        add_page = self.client.get('/admin/auth/user/add/')

        self.assertEqual(add_page.status_code, 200)

    def test_products_page_has_a_stock_management_action(self):
        response = self.client.get('/products/')

        self.assertContains(response, 'data-restock-supply')
        self.assertContains(response, 'Modificar stock')

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

    def test_homepage_is_distinct_from_catalog(self):
        home_response = self.client.get('/')
        catalog_response = self.client.get('/products/')

        self.assertContains(home_response, 'Explora por categoría')
        self.assertContains(catalog_response, 'Buscar en el catálogo')
        self.assertNotEqual(home_response.content, catalog_response.content)

    @patch('academic.views.SupplyCategory.objects.annotate', side_effect=OperationalError('database unavailable'))
    def test_homepage_still_renders_when_catalog_database_fails(self, _annotate):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No se pudo conectar con el catálogo')

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
