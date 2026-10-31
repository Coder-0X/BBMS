from django.contrib import admin
from .models import (
    ComponentType, BloodUnit, ProcessingEvent,
    UnitLineage, UnitStateTransition, UnitStatusEvent,
    LabelTemplate, LabelPrintLog, Transfer,
)


@admin.register(ComponentType)
class ComponentTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'shelf_life_hours', 'component_class')


@admin.register(BloodUnit)
class BloodUnitAdmin(admin.ModelAdmin):
    list_display  = ('did', 'abo_type', 'rh_d_type', 'component_type', 'status', 'expiry_datetime', 'owner_branch')
    list_filter   = ('status', 'abo_type', 'rh_d_type', 'component_type')
    search_fields = ('did',)
    readonly_fields = ('did', 'version', 'donation')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UnitStatusEvent)
class UnitStatusEventAdmin(admin.ModelAdmin):
    list_display = ('unit', 'from_status', 'to_status', 'actor', 'occurred_at')
    readonly_fields = ('unit', 'from_status', 'to_status', 'actor', 'occurred_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(UnitStateTransition)
class UnitStateTransitionAdmin(admin.ModelAdmin):
    list_display = ('from_status', 'to_status', 'requires_permission')


@admin.register(ProcessingEvent)
class ProcessingEventAdmin(admin.ModelAdmin):
    list_display = ('pk', 'event_type', 'performed_by', 'performed_at')


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ('blood_unit', 'from_branch', 'to_branch', 'status', 'dispatched_at')
    list_filter  = ('status',)
