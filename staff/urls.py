from django.urls import path

from . import views

urlpatterns = [
    path('', views.StaffListView.as_view(), name='staff_list'),
    path('add/', views.StaffCreateView.as_view(), name='staff_add'),
    path('<int:pk>/edit/', views.StaffUpdateView.as_view(), name='staff_edit'),
    path(
        '<int:pk>/delete/',
        views.StaffDeleteView.as_view(),
        name='staff_delete',
    ),
    path('audit/', views.AuditLogListView.as_view(), name='audit_list'),
    path('audit/add/', views.AuditLogCreateView.as_view(), name='audit_add'),
    path(
        'audit/<int:pk>/edit/',
        views.AuditLogUpdateView.as_view(),
        name='audit_edit',
    ),
    path(
        'audit/<int:pk>/delete/',
        views.AuditLogDeleteView.as_view(),
        name='audit_delete',
    ),
]
