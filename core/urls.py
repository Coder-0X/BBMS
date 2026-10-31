from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('reports/', views.reports_view, name='reports'),
    path('reports/<str:report_type>/pdf/', views.export_report_pdf, name='export_report_pdf'),
    path('branches/', views.branch_list, name='branch_list'),
    path('branches/new/', views.branch_create, name='branch_create'),
    path('branches/select/', views.select_branch, name='select_branch'),
    path('audit/', views.audit_log_view, name='audit_log'),
    path('audit/verify-chain/', views.audit_chain_verify, name='audit_chain_verify'),
    path('alerts/', views.alerts_view, name='alerts'),
    path('config-targets/', views.config_target_list, name='config_target_list'),
    path('config-targets/new/', views.config_target_form, name='config_target_new'),
    path('config-targets/<int:pk>/edit/', views.config_target_form, name='config_target_edit'),
    path('config-targets/<int:pk>/delete/', views.config_target_delete, name='config_target_delete'),
    path('mci/', views.mci_status, name='mci'),
    path('reports/tat/', views.tat_report, name='tat_report'),
    path('reports/quality-indicators/', views.quality_indicators, name='quality_indicators'),
]
