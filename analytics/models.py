"""
Analytics models — one row per component-class per branch per day.
Written by the build_daily_facts management command (run nightly).
"""
from django.db import models


COMPONENT_CLASSES = [
    ('RBC', 'Red Blood Cells'),
    ('FFP', 'Fresh Frozen Plasma'),
    ('PLT', 'Platelets'),
    ('CRYO', 'Cryoprecipitate'),
    ('WB', 'Whole Blood'),
    ('GRAN', 'Granulocytes'),
]


class DemandFactDaily(models.Model):
    """
    One row per (branch, component_class, date).
    Captures what happened: issues, crossmatches, donations received, opening/closing stock.
    """
    branch          = models.ForeignKey('core.Branch', on_delete=models.CASCADE, related_name='+')
    component_class = models.CharField(max_length=5, choices=COMPONENT_CLASSES)
    fact_date       = models.DateField(db_index=True)

    units_issued        = models.SmallIntegerField(default=0)
    units_crossmatched  = models.SmallIntegerField(default=0)
    units_expired       = models.SmallIntegerField(default=0)
    units_discarded     = models.SmallIntegerField(default=0)
    units_received      = models.SmallIntegerField(default=0)
    opening_stock       = models.SmallIntegerField(default=0)
    closing_stock       = models.SmallIntegerField(default=0)

    class Meta:
        unique_together = [('branch', 'component_class', 'fact_date')]
        ordering = ['-fact_date']

    def __str__(self):
        return f"{self.branch} / {self.component_class} / {self.fact_date}: {self.units_issued} issued"


class Forecast(models.Model):
    """
    Holt-Winters additive forecast: predicted demand N days ahead.
    One row per (branch, component_class, horizon_date, generated_on).
    """
    branch              = models.ForeignKey('core.Branch', on_delete=models.CASCADE, related_name='+')
    component_class     = models.CharField(max_length=5, choices=COMPONENT_CLASSES)
    generated_on        = models.DateField()
    horizon_date        = models.DateField()
    predicted_units     = models.DecimalField(max_digits=7, decimal_places=2)
    lower_80            = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    upper_80            = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    model_params        = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = [('branch', 'component_class', 'generated_on', 'horizon_date')]
        ordering = ['horizon_date']

    def __str__(self):
        return (f"Forecast {self.branch}/{self.component_class} "
                f"for {self.horizon_date}: {self.predicted_units:.1f} units")


class KpiDaily(models.Model):
    """
    Daily computed KPIs per branch (one row per branch per day).
    """
    branch          = models.ForeignKey('core.Branch', on_delete=models.CASCADE, related_name='+')
    kpi_date        = models.DateField()
    ct_ratio_rbc    = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ct_ratio_plt    = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ct_ratio_ffp    = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    wastage_pct_rbc = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    wastage_pct_plt = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    days_supply_rbc = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    days_supply_plt = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    days_supply_ffp = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)

    class Meta:
        unique_together = [('branch', 'kpi_date')]
        ordering = ['-kpi_date']

    def __str__(self):
        return f"KPI {self.branch} {self.kpi_date}"
