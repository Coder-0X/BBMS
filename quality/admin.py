from django.contrib import admin
from .models import Reagent, ReagentLot, QCRun, QCResult, EquipmentCalibration


class QCResultInline(admin.TabularInline):
    model = QCResult
    extra = 0


@admin.register(Reagent)
class ReagentAdmin(admin.ModelAdmin):
    list_display = ('name', 'reagent_code', 'category', 'qc_interval_hours', 'active')
    list_filter = ('category', 'active')


@admin.register(ReagentLot)
class ReagentLotAdmin(admin.ModelAdmin):
    list_display = ('reagent', 'lot_number', 'expiry_date', 'status', 'branch', 'received_at')
    list_filter = ('status', 'branch')


@admin.register(QCRun)
class QCRunAdmin(admin.ModelAdmin):
    list_display = ('reagent', 'lot', 'overall_pass', 'protocol', 'completed_at', 'performed_by', 'branch')
    list_filter = ('overall_pass', 'protocol', 'branch')
    inlines = [QCResultInline]
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EquipmentCalibration)
class EquipmentCalibrationAdmin(admin.ModelAdmin):
    list_display = ('name', 'asset_id', 'equipment_type', 'last_calibrated', 'next_due', 'within_spec', 'branch')
    list_filter = ('equipment_type', 'within_spec', 'branch')
