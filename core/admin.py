from django.contrib import admin
from .models import Branch, RefFacility

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ['name', 'facility_code', 'active']
    list_filter = ['active']

@admin.register(RefFacility)
class RefFacilityAdmin(admin.ModelAdmin):
    list_display = ['facility_code', 'name', 'branch', 'last_serial']
    readonly_fields = ['last_serial']
