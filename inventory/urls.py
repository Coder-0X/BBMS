from django.urls import path
from . import views
from . import views_recall

app_name = 'inventory'

urlpatterns = [
    path('units/', views.unit_list, name='unit_list'),
    # Static unit paths must come BEFORE the <str:did> wildcard
    path('units/antigen-match/', views.antigen_match_search, name='antigen_match_search'),
    path('units/pool-platelets/', views.pool_platelets, name='pool_platelets'),
    path('near-expiry/', views.near_expiry_units, name='near_expiry'),
    path('wastage-report/', views.wastage_report, name='wastage_report'),
    path('cross-site-request/', views.cross_site_request, name='cross_site_request'),
    # Unit detail and sub-actions (wildcard <str:did>)
    path('units/<str:did>/', views.unit_detail, name='unit_detail'),
    path('units/<str:did>/process/', views.record_processing, name='record_processing'),
    path('units/<str:did>/status/', views.change_unit_status, name='change_status'),
    path('units/<str:did>/transfer/', views.initiate_transfer, name='initiate_transfer'),
    path('units/<str:did>/label/', views.print_label_view, name='print_label'),
    path('units/<str:did>/pil.pdf', views.export_unit_pil, name='unit_pil'),
    path('units/<str:did>/wastage/', views.record_wastage, name='record_wastage'),
    path('units/<str:did>/irradiate/', views.irradiate_unit, name='irradiate_unit'),
    path('units/<str:did>/leukoreduction/', views.leukoreduction_unit, name='leukoreduction_unit'),
    path('units/<str:did>/wash/', views.wash_unit, name='wash_unit'),
    # Other resources
    path('donations/<int:donation_id>/separate/', views.separate_components, name='separate_components'),
    path('recall/', views_recall.recall_lookup, name='recall_lookup'),
    path('recall/<int:donation_id>/execute/', views_recall.recall_execute, name='recall_execute'),
    path('transfers/', views.pending_transfers, name='pending_transfers'),
    path('transfers/<int:transfer_pk>/receive/', views.receive_transfer, name='receive_transfer'),
]
