"""Rutas globales del proyecto Django."""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenRefreshView

from academic import views
from academic.admin import superuser_admin_site
from academic.authentication import RoleTokenObtainPairView
from academic.permissions import IsSuperUser

urlpatterns = [
    # Panel de administración opcional de Django.
    path('admin/', superuser_admin_site.urls),
    path('favicon.ico', views.favicon, name='favicon'),
    # Páginas visibles para el cliente de la tienda.
    path('', views.home, name='home'),
    path('products/', views.products_page, name='products'),
    path('cart/', views.cart_page, name='cart'),
    path('login/', views.login_page, name='login'),
    path('register/', views.register_page, name='register'),
    path('gestor/', views.warehouse_dashboard_page, name='warehouse-dashboard'),
    path('inventario/', views.inventory_management_page, name='inventory-management'),
    path('pedidos/', views.order_management_page, name='order-management'),
    path('api/cart/', views.MedicalCartView.as_view(), name='cart-api-legacy-alias'),
    # Endpoints para autenticación JWT.
    path('api/token/', RoleTokenObtainPairView.as_view(), name='token-obtain-pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('api/docs/session/', views.DocumentationSessionView.as_view(), name='docs-session'),
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[IsSuperUser]), name='schema'),
    path(
        'api/docs/',
        SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[IsSuperUser]),
        name='swagger-ui',
    ),
    path(
        'doc/',
        SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[IsSuperUser]),
        name='swagger-ui-short',
    ),
    # La API separa lectura pública, clientes institucionales y gestión de bodega.
    path('api/', include('academic.urls')),
]

# Django utiliza esta vista cuando ninguna URL coincide.
handler404 = 'academic.views.error_404'
