from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Role, Permission, UserRole, SoDConflict, BreakGlassSession


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'display_name', 'branch', 'mfa_enabled', 'is_active', 'is_locked']
    list_filter = ['is_active', 'mfa_enabled', 'branch']
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Info', {'fields': ('display_name', 'branch')}),
        ('MFA', {'fields': ('mfa_enabled',)}),
        ('Security', {'fields': ('failed_attempts', 'locked_until')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    readonly_fields = ['failed_attempts', 'locked_until']
    add_fieldsets = (
        (None, {'fields': ('username', 'password1', 'password2', 'display_name', 'branch')}),
    )
    search_fields = ['username', 'display_name']
    ordering = ['username']


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['code', 'description']
    search_fields = ['code']


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['name', 'branch_scoped']
    filter_horizontal = ['permissions']


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'branch', 'granted_at', 'revoked_at']
    list_filter = ['role', 'branch']


@admin.register(SoDConflict)
class SoDConflictAdmin(admin.ModelAdmin):
    list_display = ['permission_a', 'permission_b', 'reason']


@admin.register(BreakGlassSession)
class BreakGlassSessionAdmin(admin.ModelAdmin):
    list_display = ['user', 'reason_code', 'granted_at', 'expires_at', 'reviewed_by']
    list_filter = ['reason_code']
