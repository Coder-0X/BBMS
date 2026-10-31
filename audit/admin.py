from django.contrib import admin
from .models import AuditLog, AuditChainAnchor, ElectronicSignature


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['seq', 'occurred_at_utc', 'actor', 'action', 'entity_table', 'entity_id']
    list_filter = ['action', 'source']
    search_fields = ['action', 'entity_table']
    readonly_fields = [f.name for f in AuditLog._meta.get_fields()]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditChainAnchor)
class AuditChainAnchorAdmin(admin.ModelAdmin):
    list_display = ['chain_head_seq', 'anchored_at']
    readonly_fields = [f.name for f in AuditChainAnchor._meta.get_fields()]


@admin.register(ElectronicSignature)
class ElectronicSignatureAdmin(admin.ModelAdmin):
    list_display = ['manifested_name', 'meaning', 'signed_at_utc', 'auth_method']
    list_filter = ['meaning', 'auth_method']
    readonly_fields = [f.name for f in ElectronicSignature._meta.get_fields()]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
