from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('mfa/verify/', views.mfa_verify_view, name='mfa_verify'),
    path('mfa/setup/', views.mfa_setup_view, name='mfa_setup'),
    path('reauth/', views.reauth_view, name='reauth'),
    path('password/change/', views.change_password_view, name='change_password'),
    path('users/', views.user_list_view, name='user_list'),
    path('users/new/', views.user_create_view, name='user_create'),
    path('users/<int:pk>/', views.user_detail_view, name='user_detail'),
    path('roles/', views.role_list_view, name='role_list'),
    path('roles/new/', views.role_create_view, name='role_create'),
    path('permissions/', views.permission_list_view, name='permission_list'),
    path('sod/', views.sod_manage_view, name='sod_manage'),
    path('notifications/', views.notification_settings_view, name='notification_settings'),
]
