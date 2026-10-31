from django.contrib import admin
from .models import (
    ComponentStorageSpec, StorageEquipment, SensorHealth, TemperatureLog,
    TemperatureExcursion, ExcursionUnitLink, EquipmentAlarm, UnitReturnCheck,
    ShipmentColdChain,
)


@admin.register(ComponentStorageSpec)
class ComponentStorageSpecAdmin(admin.ModelAdmin):
    list_display = ['component_class', 'storage_temp_min_c', 'storage_temp_max_c',
                    'requires_agitation', 'shelf_life_hours']


@admin.register(StorageEquipment)
class StorageEquipmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'equipment_type', 'branch', 'status', 'sensor_id', 'calibration_due']
    list_filter = ['status', 'equipment_type', 'branch']
    search_fields = ['name', 'sensor_id']


@admin.register(SensorHealth)
class SensorHealthAdmin(admin.ModelAdmin):
    list_display = ['sensor_id', 'equipment', 'status', 'last_seen_at']
    list_filter = ['status']


@admin.register(TemperatureLog)
class TemperatureLogAdmin(admin.ModelAdmin):
    list_display = ['equipment', 'recorded_at', 'temp_c', 'source']
    list_filter = ['equipment', 'source']
    date_hierarchy = 'recorded_at'


class ExcursionUnitLinkInline(admin.TabularInline):
    model = ExcursionUnitLink
    extra = 0


class EquipmentAlarmInline(admin.TabularInline):
    model = EquipmentAlarm
    extra = 0


@admin.register(TemperatureExcursion)
class TemperatureExcursionAdmin(admin.ModelAdmin):
    list_display = ['equipment', 'started_at', 'ended_at', 'max_temp_c', 'disposition', 'auto_quarantine']
    list_filter = ['disposition', 'auto_quarantine', 'equipment']
    inlines = [ExcursionUnitLinkInline, EquipmentAlarmInline]


@admin.register(EquipmentAlarm)
class EquipmentAlarmAdmin(admin.ModelAdmin):
    list_display = ['equipment', 'alarm_type', 'triggered_at', 'cleared_at', 'escalation_level']
    list_filter = ['alarm_type', 'escalation_level']


@admin.register(UnitReturnCheck)
class UnitReturnCheckAdmin(admin.ModelAdmin):
    list_display = ['blood_unit', 'decision', 'minutes_out', 'rule_applied', 'decided_by', 'created_at']
    list_filter = ['decision', 'rule_applied']


@admin.register(ShipmentColdChain)
class ShipmentColdChainAdmin(admin.ModelAdmin):
    list_display = ['transfer', 'origin_branch', 'destination_branch', 'departed_at', 'excursion_detected']
    list_filter = ['excursion_detected']
