from django.contrib import admin
from .models import DemandFactDaily, Forecast, KpiDaily


@admin.register(DemandFactDaily)
class DemandFactDailyAdmin(admin.ModelAdmin):
    list_display = ['branch', 'component_class', 'fact_date', 'units_issued',
                    'units_expired', 'opening_stock', 'closing_stock']
    list_filter = ['branch', 'component_class']
    date_hierarchy = 'fact_date'


@admin.register(Forecast)
class ForecastAdmin(admin.ModelAdmin):
    list_display = ['branch', 'component_class', 'generated_on', 'horizon_date', 'predicted_units']
    list_filter = ['branch', 'component_class']


@admin.register(KpiDaily)
class KpiDailyAdmin(admin.ModelAdmin):
    list_display = ['branch', 'kpi_date', 'ct_ratio_rbc', 'wastage_pct_rbc', 'days_supply_rbc']
    list_filter = ['branch']
    date_hierarchy = 'kpi_date'
