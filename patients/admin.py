from django.contrib import admin
from .models import Patient, PatientIdentifier, PatientBloodGroup, PatientAntibody, PatientTransfusionRequirement


class PatientIdentifierInline(admin.TabularInline):
    model = PatientIdentifier
    extra = 0


class PatientSpecialReqInline(admin.TabularInline):
    model = PatientTransfusionRequirement
    extra = 0
    readonly_fields = ('set_by', 'set_at', 'revoked_by', 'revoked_at')


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display  = ('pk', 'mpi_uid', 'sex', 'record_status', 'created_at')
    search_fields = ('mpi_uid',)
    list_filter   = ('record_status', 'sex')
    readonly_fields = ('mpi_uid', 'created_at', 'created_by')
    inlines = [PatientIdentifierInline, PatientSpecialReqInline]


@admin.register(PatientBloodGroup)
class PatientBloodGroupAdmin(admin.ModelAdmin):
    list_display    = ('patient', 'abo', 'rh_d', 'is_discrepant', 'determined_at', 'source')
    list_filter     = ('abo', 'rh_d', 'is_discrepant', 'source')
    readonly_fields = ('determined_at',)

    def has_change_permission(self, request, obj=None):
        return False  # append-only


@admin.register(PatientAntibody)
class PatientAntibodyAdmin(admin.ModelAdmin):
    list_display = ('patient', 'specificity', 'antigen_system', 'clinical_significance', 'status', 'evanescent')
    list_filter  = ('clinical_significance', 'status', 'evanescent')
    search_fields = ('specificity', 'antigen_system')

    def has_change_permission(self, request, obj=None):
        return False  # append-only
