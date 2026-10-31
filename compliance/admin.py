from django.contrib import admin
from .models import ComplianceJurisdiction, ComplianceRuleset, ComplianceRule, RetentionPolicy


@admin.register(ComplianceJurisdiction)
class JurisdictionAdmin(admin.ModelAdmin):
    list_display = ['country_code', 'name']


@admin.register(ComplianceRuleset)
class RulesetAdmin(admin.ModelAdmin):
    list_display = ['jurisdiction', 'version', 'status', 'effective_from', 'locked']
    list_filter = ['status', 'jurisdiction']
    readonly_fields = ['locked', 'created_at']


@admin.register(ComplianceRule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ['ruleset', 'rule_kind', 'operator', 'threshold_value', 'threshold_unit']
    list_filter = ['ruleset', 'rule_kind', 'applies_to']


@admin.register(RetentionPolicy)
class RetentionPolicyAdmin(admin.ModelAdmin):
    list_display = ['record_class', 'min_retention_years', 'indefinite']
