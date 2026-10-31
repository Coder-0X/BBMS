from django.db import models
from django.conf import settings


class Branch(models.Model):
    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    facility_code = models.CharField(max_length=3, unique=True)
    timezone = models.CharField(max_length=50, default='UTC')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    jurisdiction = models.ForeignKey(
        'compliance.ComplianceJurisdiction',
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='branches',
    )
    active_ruleset = models.ForeignKey(
        'compliance.ComplianceRuleset',
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )

    class Meta:
        verbose_name_plural = 'branches'

    def __str__(self):
        return f"{self.name} ({self.facility_code})"


class RefFacility(models.Model):
    facility_code = models.CharField(max_length=3, primary_key=True)
    name = models.CharField(max_length=200)
    branch = models.OneToOneField(Branch, on_delete=models.PROTECT, related_name='facility')
    last_serial = models.IntegerField(default=0)

    def next_serial(self) -> int:
        self.last_serial = models.F('last_serial') + 1
        self.save(update_fields=['last_serial'])
        self.refresh_from_db()
        return self.last_serial

    def __str__(self):
        return f"{self.facility_code} — {self.name}"


class Alert(models.Model):
    TYPES = [
        ('low_inventory', 'Low Inventory'),
        ('near_expiry', 'Near Expiry'),
        ('reactive_result', 'Reactive Test Result'),
        ('pending_recall', 'Pending Recall'),
        ('high_wastage', 'High Wastage'),
        ('pending_emergency_review', 'Pending Emergency Release Review'),
        ('ct_ratio_high', 'C:T Ratio Too High'),
        ('unit_expired', 'Unit Expired'),
        ('blood_group_discrepancy', 'Blood Group Discrepancy'),
        ('donor_deferral_lapsed', 'Deferred Donor Eligible Again'),
        ('mci_active', 'MCI Activated'),
        ('mci_stood_down', 'MCI Stood Down'),
        ('critical_stock', 'Critical Stock Level'),
        ('qc_failure', 'Reagent QC Failure'),
        ('reagent_overdue_qc', 'Reagent QC Overdue'),
        ('equipment_calibration_due', 'Equipment Calibration Due'),
        ('lapsed_donors', 'Lapsed Donor Re-engagement Due'),
        ('ungrouped_units', 'Ungrouped Blood Units'),
        ('forecast_shortage', 'Forecast Shortage (Predicted)'),
        ('sensor_offline', 'Temperature Sensor Offline'),
        ('calibration_overdue', 'Cold Chain Calibration Overdue'),
        ('ongoing_excursion', 'Active Temperature Excursion'),
        ('sop_review_overdue', 'SOP Periodic Review Overdue'),
        ('competency_overdue', 'Staff Competency Re-assessment Overdue'),
        ('nc_backlog', 'Non-Conformance Backlog'),
        ('raadp_overdue', 'Routine Antenatal Anti-D Prophylaxis Overdue'),
        ('lookback_pending', 'Lookback Campaign — Pending Notifications'),
        ('committee_action_overdue', 'Transfusion Committee Action Overdue'),
        ('hdfn_unreported', 'HDFN Severe Case — Haemovigilance Not Reported'),
        ('pbm_post_hb_gap', 'PBM Programme — Post-Hb Documentation Gap'),
        ('consent_withdrawn', 'Patient Consent Withdrawn'),
        ('dsr_received', 'Data Subject Rights Request Received'),
        ('crossmatch_expiring', 'Crossmatch Sample Expiring Soon'),
    ]
    SEVERITIES = [('info', 'Info'), ('warning', 'Warning'), ('critical', 'Critical')]

    alert_type = models.CharField(max_length=40, choices=TYPES)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='alerts')
    severity = models.CharField(max_length=10, choices=SEVERITIES)
    message = models.CharField(max_length=500)
    entity_table = models.CharField(max_length=100, blank=True)
    entity_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.severity.upper()}] {self.alert_type} @ {self.branch}"


class MCIEvent(models.Model):
    """
    Mass Casualty Incident activation record.
    When active: crossmatch requirements are relaxed, O-neg is pre-allocated,
    all staff receive an alert, and the dashboard shows a red banner.
    """
    STATUSES = [('active', 'Active'), ('stood_down', 'Stood Down')]
    LEVELS   = [('1', 'Level 1 — Internal (single ward)'),
                ('2', 'Level 2 — Major (multi-ward / hospital-wide)'),
                ('3', 'Level 3 — Mass Casualty (>20 casualties)')]

    branch          = models.ForeignKey('Branch', on_delete=models.PROTECT, related_name='mci_events')
    level           = models.CharField(max_length=1, choices=LEVELS, default='2')
    incident_name   = models.CharField(max_length=200, blank=True)
    status          = models.CharField(max_length=15, choices=STATUSES, default='active')
    activated_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    activated_at    = models.DateTimeField()
    stood_down_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    stood_down_at   = models.DateTimeField(null=True, blank=True)
    # Units pre-allocated: list of BloodUnit PKs
    preallocated_unit_pks = models.JSONField(default=list)
    notes           = models.TextField(blank=True)
    esign_activate  = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    esign_standdown = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT, related_name='+')

    class Meta:
        ordering = ['-activated_at']

    def __str__(self):
        return f"MCI-{self.pk} {self.get_level_display()} @ {self.branch} ({self.status})"

    @classmethod
    def active_for_branch(cls, branch_id):
        return cls.objects.filter(branch_id=branch_id, status='active').first()


class ConfigTarget(models.Model):
    """Per-branch KPI targets for inventory management."""
    CLASSES = [('RBC','RBC'),('FFP','FFP'),('PLT','PLT'),('CRYO','CRYO'),('WB','WB'),('GRAN','GRAN')]

    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name='config_targets')
    component_class = models.CharField(max_length=5, choices=CLASSES)
    target_days_of_supply = models.DecimalField(max_digits=5, decimal_places=2, default=3.0)
    max_wastage_pct = models.DecimalField(max_digits=5, decimal_places=2, default=5.0)
    near_expiry_alert_hours = models.SmallIntegerField(default=72)
    max_ct_ratio = models.DecimalField(max_digits=5, decimal_places=2, default=2.5, help_text="Crossmatch-to-transfusion ratio above which an alert fires")
    abo_distribution = models.JSONField(null=True, blank=True)
    safety_quantile = models.DecimalField(max_digits=4, decimal_places=3, default=0.950)

    class Meta:
        unique_together = [('branch', 'component_class')]

    def __str__(self):
        scope = self.branch.name if self.branch else "System-wide"
        return f"{scope} / {self.component_class}"
