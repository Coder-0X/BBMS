from django.contrib import admin
from .models import Donor, Donation, DonorAdverseEvent


class DonationInline(admin.TabularInline):
    model = Donation
    extra = 0
    readonly_fields = ('collected_by', 'donated_at')


@admin.register(Donor)
class DonorAdmin(admin.ModelAdmin):
    list_display = ('pk', 'deferral_status', 'first_donation_date', 'total_donations')
    list_filter  = ('deferral_status',)
    inlines = [DonationInline]


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ('pk', 'donor', 'donation_type', 'volume_ml', 'collected_by', 'donated_at')
    list_filter  = ('donation_type',)
    search_fields = ('pk',)


@admin.register(DonorAdverseEvent)
class DonorAdverseEventAdmin(admin.ModelAdmin):
    list_display = ('donor', 'event_type', 'severity', 'recorded_at')
    list_filter  = ('event_type', 'severity')
