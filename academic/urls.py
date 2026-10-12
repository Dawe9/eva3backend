"""Endpoints de catálogo, carro y solicitudes B2B de farmacia."""

from django.urls import path

from . import views

urlpatterns = [
    path('registro/', views.InstitutionRegistrationView.as_view(), name='institution-registration'),
    path('categorias/', views.SupplyCategoryListCreateView.as_view(), name='category-list'),
    path('categorias/<int:pk>/', views.SupplyCategoryDetailView.as_view(), name='category-detail'),
    path('insumos/', views.MedicalSupplyListCreateView.as_view(), name='supply-list'),
    path('insumos/<int:pk>/', views.MedicalSupplyDetailView.as_view(), name='supply-detail'),
    path('insumos/<int:pk>/agregar-stock/', views.MedicalSupplyRestockView.as_view(), name='supply-restock'),
    path('carro-insumos/', views.MedicalCartView.as_view(), name='medical-cart'),
    path('solicitudes/confirmar/', views.PurchaseRequestCheckoutView.as_view(), name='request-checkout'),
    path('mis-solicitudes/', views.MyPurchaseRequestsView.as_view(), name='my-requests'),
    path('solicitudes/', views.WarehousePurchaseRequestsView.as_view(), name='warehouse-requests'),
    path('solicitudes/<int:pk>/estado/', views.PurchaseRequestStatusView.as_view(), name='request-status'),
]
