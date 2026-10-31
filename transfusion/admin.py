from django.contrib import admin
from .models import (
    TestDefinition, Sample, DonationTestResult,
    AntibodyScreen, AntibodyIdentification,
    MSBOS, BloodRequest, Crossmatch, IssueTransaction, EmergencyRelease,
    TransfusionReaction, TransfusionAdministration,
)


@admin.register(TestDefinition)
class TestDefinitionAdmin(admin.ModelAdmin):
    list_display = ('test_code', 'name', 'pathogen', 'method', 'mandatory', 'applies_to')


@admin.register(Sample)
class SampleAdmin(admin.ModelAdmin):
    list_display = ('accession_number', 'sample_type', 'patient', 'donor', 'collected_at', 'is_valid')
    list_filter  = ('sample_type',)
    search_fields = ('accession_number',)


@admin.register(DonationTestResult)
class DonationTestResultAdmin(admin.ModelAdmin):
    list_display = ('donation', 'test', 'result', 'performed_by', 'performed_at')
    list_filter  = ('result',)

    def has_change_permission(self, request, obj=None):
        return False  # test results are immutable


@admin.register(BloodRequest)
class BloodRequestAdmin(admin.ModelAdmin):
    list_display = ('pk', 'patient', 'component_class', 'units_requested', 'urgency', 'outcome', 'requested_ts')
    list_filter  = ('component_class', 'urgency', 'outcome')


@admin.register(Crossmatch)
class CrossmatchAdmin(admin.ModelAdmin):
    list_display = ('blood_unit', 'request', 'method', 'result', 'tech', 'performed_at')
    list_filter  = ('method', 'result')


@admin.register(IssueTransaction)
class IssueTransactionAdmin(admin.ModelAdmin):
    list_display = ('blood_unit', 'patient', 'request', 'issued_by', 'issued_at', 'abo_check_passed')
    readonly_fields = ('blood_unit', 'patient', 'request', 'issued_by', 'issue_esign', 'issued_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EmergencyRelease)
class EmergencyReleaseAdmin(admin.ModelAdmin):
    list_display = ('pk', 'patient', 'physician', 'signoff_status', 'retrospective_xm_status', 'release_datetime')
    list_filter  = ('signoff_status', 'retrospective_xm_status')

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MSBOS)
class MSBOSAdmin(admin.ModelAdmin):
    list_display = ('procedure_code', 'branch', 'order_type', 'units_count')


@admin.register(TransfusionReaction)
class TransfusionReactionAdmin(admin.ModelAdmin):
    list_display = ('pk', 'blood_unit', 'patient', 'reaction_type', 'severity', 'imputability', 'outcome', 'recorded_at')
    list_filter  = ('reaction_type', 'severity', 'imputability', 'outcome')
    readonly_fields = ('recorded_by', 'recorded_at', 'esign')


@admin.register(TransfusionAdministration)
class TransfusionAdministrationAdmin(admin.ModelAdmin):
    list_display = ('pk', 'blood_unit', 'patient', 'outcome', 'bedside_verify_pass', 'start_at', 'created_at')
    list_filter  = ('outcome', 'bedside_verify_pass')
    readonly_fields = ('created_at',)

    def has_change_permission(self, request, obj=None):
        return False
