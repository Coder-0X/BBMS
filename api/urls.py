from django.urls import path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register('branches',     views.BranchViewSet,          basename='branch')
router.register('components',   views.ComponentTypeViewSet,   basename='component')
router.register('donors',       views.DonorViewSet,           basename='donor')
router.register('units',        views.BloodUnitViewSet,       basename='unit')
router.register('patients',     views.PatientViewSet,         basename='patient')
router.register('requests',     views.BloodRequestViewSet,    basename='request')
router.register('samples',      views.SampleViewSet,          basename='sample')
router.register('transactions', views.IssueTransactionViewSet, basename='transaction')
router.register('alerts',       views.AlertViewSet,           basename='alert')

urlpatterns = router.urls + [
    path('health/', views.HealthView.as_view(), name='api_health'),
    path('auth/token/', views.TokenView.as_view(), name='api_token'),
    path('temperature/', views.TemperatureIngestView.as_view(), name='api_temperature_ingest'),
    path('bedside/verify/', views.BedsideVerifyView.as_view(), name='api_bedside_verify'),
]
