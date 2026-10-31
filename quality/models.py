from django.db import models
from django.conf import settings


REAGENT_CATEGORIES = [
    ('grouping',   'Blood Grouping Sera'),
    ('coombs',     'Antiglobulin (Coombs)'),
    ('screening',  'Screening Cells'),
    ('id_panel',   'Identification Panel Cells'),
    ('enzyme',     'Enzyme (Papain/Ficin)'),
    ('other',      'Other'),
]

# Expected reaction for each reagent with the appropriate control cell
# Used to validate QC entries
REAGENT_QC_EXPECTATION = {
    'anti_A':    {'pos_control': '4+', 'neg_control': '0'},
    'anti_B':    {'pos_control': '4+', 'neg_control': '0'},
    'anti_D':    {'pos_control': '3+', 'neg_control': '0'},
    'anti_AB':   {'pos_control': '4+', 'neg_control': '0'},
    'ahg_poly':  {'pos_control': '2+', 'neg_control': '0'},
    'ahg_igg':   {'pos_control': '2+', 'neg_control': '0'},
    'ahg_c3d':   {'pos_control': '2+', 'neg_control': '0'},
}

REACTION_GRADES = [
    ('0',   '0 — No agglutination'),
    ('w+',  'w+ — Weak'),
    ('1+',  '1+'),
    ('2+',  '2+'),
    ('3+',  '3+'),
    ('4+',  '4+ — Strong'),
    ('hem', 'Haemolysis'),
    ('mf',  'Mixed field'),
]


class Reagent(models.Model):
    """A class of reagent kept in stock (not a specific lot)."""
    name            = models.CharField(max_length=100)
    category        = models.CharField(max_length=20, choices=REAGENT_CATEGORIES)
    reagent_code    = models.CharField(max_length=30, unique=True)
    manufacturer    = models.CharField(max_length=100, blank=True)
    # Minimum daily QC: must have a passing QC run within this many hours
    qc_interval_hours  = models.SmallIntegerField(default=24)
    # Low-stock threshold: alert if fewer than this many active+quarantined lots exist
    minimum_lots       = models.SmallIntegerField(default=1, help_text="Alert when fewer than this many lots are available (in_use + quarantined)")
    active          = models.BooleanField(default=True)
    notes           = models.TextField(blank=True)

    def current_lot(self):
        return self.lots.filter(status='in_use').order_by('-opened_at').first()

    def qc_status(self, branch_id=None):
        """'pass', 'fail', 'overdue', or 'no_data'."""
        from django.utils import timezone
        from datetime import timedelta as _td
        cutoff = timezone.now() - _td(hours=self.qc_interval_hours)
        qs = QCRun.objects.filter(reagent=self, completed_at__gte=cutoff)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if not qs.exists():
            return 'overdue'
        if qs.filter(overall_pass=False).exists():
            return 'fail'
        return 'pass'

    def __str__(self):
        return f"{self.name} ({self.reagent_code})"


class ReagentLot(models.Model):
    """A specific lot/batch of a reagent."""
    STATUS = [
        ('quarantined', 'Quarantined — awaiting QC'),
        ('in_use',      'In Use — QC passed'),
        ('depleted',    'Depleted'),
        ('recalled',    'Recalled by manufacturer'),
        ('expired',     'Expired'),
        ('rejected',    'Rejected — failed QC'),
    ]

    reagent         = models.ForeignKey(Reagent, on_delete=models.PROTECT, related_name='lots')
    lot_number      = models.CharField(max_length=50)
    expiry_date     = models.DateField()
    received_at     = models.DateField()
    opened_at       = models.DateField(null=True, blank=True)
    in_use_expiry   = models.DateField(null=True, blank=True, help_text='Expiry once opened')
    status          = models.CharField(max_length=15, choices=STATUS, default='quarantined')
    received_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    branch          = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    certificate_ok  = models.BooleanField(default=False, help_text='Certificate of Analysis reviewed')
    notes           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('reagent', 'lot_number')]

    def is_expired(self):
        from django.utils import timezone
        today = timezone.now().date()
        if self.in_use_expiry and self.opened_at:
            return today > self.in_use_expiry
        return today > self.expiry_date

    def __str__(self):
        return f"{self.reagent.name} — Lot {self.lot_number} ({self.status})"


class QCRun(models.Model):
    """A daily QC testing session for one or more reagents."""
    reagent         = models.ForeignKey(Reagent, on_delete=models.PROTECT, related_name='qc_runs')
    lot             = models.ForeignKey(ReagentLot, on_delete=models.PROTECT, related_name='qc_runs')
    branch          = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    performed_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reviewed_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    started_at      = models.DateTimeField()
    completed_at    = models.DateTimeField()
    overall_pass    = models.BooleanField()
    # QC protocol used (e.g. 'daily_grouping', 'new_lot_validation')
    protocol        = models.CharField(max_length=50, default='daily')
    failure_action  = models.TextField(blank=True, help_text='Action taken if QC failed')
    notes           = models.TextField(blank=True)
    esign           = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        result = 'PASS' if self.overall_pass else 'FAIL'
        return f"QC {result} — {self.reagent.name} — {self.completed_at:%Y-%m-%d}"


class QCResult(models.Model):
    """Individual test result within a QC run."""
    qc_run          = models.ForeignKey(QCRun, on_delete=models.CASCADE, related_name='results')
    control_type    = models.CharField(max_length=20, choices=[
        ('pos_control', 'Positive Control'),
        ('neg_control', 'Negative Control'),
        ('weak_d_ctrl', 'Weak D Control'),
    ])
    expected_grade  = models.CharField(max_length=5, choices=REACTION_GRADES)
    observed_grade  = models.CharField(max_length=5, choices=REACTION_GRADES)
    passed          = models.BooleanField()
    comment         = models.CharField(max_length=200, blank=True)

    def save(self, *args, **kwargs):
        self.passed = (self.observed_grade == self.expected_grade)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.control_type}: expected {self.expected_grade}, got {self.observed_grade} → {'PASS' if self.passed else 'FAIL'}"


class EquipmentCalibration(models.Model):
    """Calibration record for lab equipment (centrifuges, incubators, balances)."""
    EQUIPMENT_TYPES = [
        ('centrifuge',     'Centrifuge'),
        ('incubator',      'Incubator/Waterbath'),
        ('balance',        'Balance/Scale'),
        ('pipette',        'Pipette'),
        ('thermometer',    'Thermometer'),
        ('cell_washer',    'Cell Washer'),
        ('gel_centrifuge', 'Gel Card Centrifuge'),
        ('other',          'Other'),
    ]

    name            = models.CharField(max_length=100)
    asset_id        = models.CharField(max_length=50, unique=True)
    equipment_type  = models.CharField(max_length=20, choices=EQUIPMENT_TYPES)
    branch          = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    last_calibrated = models.DateField()
    next_due        = models.DateField()
    calibrated_by   = models.CharField(max_length=100)
    certificate_ref = models.CharField(max_length=100, blank=True)
    within_spec     = models.BooleanField(default=True)
    notes           = models.TextField(blank=True)
    recorded_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at      = models.DateTimeField(auto_now_add=True)

    def is_overdue(self):
        from django.utils import timezone
        return timezone.now().date() > self.next_due

    def __str__(self):
        return f"{self.name} ({self.asset_id}) — due {self.next_due}"


class NonConformance(models.Model):
    """
    Non-Conformance (NC) / Quality Event record.

    ISO 15189:2022 clause 7.7 — laboratories must identify, document, and manage
    non-conforming work.  AABB Standards 9th ed. 5.1.6 requires a documented CAPA
    (Corrective Action / Preventive Action) process.

    Severity grades (adapted from SHOT severity scale):
      near_miss  — error detected before patient impact
      minor      — minor deviation, no patient harm
      significant— significant deviation, potential for patient harm
      serious    — patient harm occurred or near-miss with high-risk potential
      critical   — death or permanent harm
    """
    NC_TYPES = [
        ('reagent_failure',        'Reagent failure / QC failure'),
        ('clerical_error',         'Clerical / labelling error'),
        ('procedure_deviation',    'SOP deviation — procedure not followed'),
        ('equipment_failure',      'Equipment failure / malfunction'),
        ('sample_issue',           'Sample integrity / mislabelling (WBIT)'),
        ('cold_chain_breach',      'Cold chain / temperature excursion'),
        ('compatibility_near_miss','Compatibility near-miss'),
        ('transfusion_reaction',   'Transfusion reaction — possible NC component'),
        ('documentation_error',    'Documentation / record-keeping error'),
        ('supply_shortage',        'Supply chain / reagent shortage'),
        ('other',                  'Other (see description)'),
    ]
    SEVERITY = [
        ('near_miss',   'Near-miss — detected before patient impact'),
        ('minor',       'Minor — no patient harm, limited impact'),
        ('significant', 'Significant — potential for patient harm'),
        ('serious',     'Serious — patient harm occurred'),
        ('critical',    'Critical — death or permanent harm'),
    ]
    STATUS = [
        ('open',        'Open'),
        ('under_review','Under Review — root cause analysis in progress'),
        ('capa_open',   'CAPA Open — corrective actions assigned'),
        ('capa_verify', 'CAPA Verification — checking effectiveness'),
        ('closed',      'Closed — verified effective'),
    ]

    nc_number         = models.CharField(max_length=20, unique=True, help_text='Auto-assigned e.g. NC-2026-0001')
    nc_type           = models.CharField(max_length=30, choices=NC_TYPES)
    severity          = models.CharField(max_length=15, choices=SEVERITY)
    status            = models.CharField(max_length=15, choices=STATUS, default='open')
    description       = models.TextField(help_text='Describe what happened, when, and where')
    immediate_action  = models.TextField(blank=True, help_text='Actions taken immediately to contain the issue')
    # Optional links to other records
    related_blood_unit_did = models.CharField(max_length=20, blank=True)
    related_patient_id     = models.IntegerField(null=True, blank=True)
    related_donor_id       = models.IntegerField(null=True, blank=True)
    related_qc_run         = models.ForeignKey('QCRun', null=True, blank=True, on_delete=models.SET_NULL, related_name='nonconformances')
    # Responsible and reporting
    reported_by       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    assigned_to       = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    branch            = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    # SHOT reportable
    shot_reportable   = models.BooleanField(default=False)
    shot_reference    = models.CharField(max_length=50, blank=True)
    # Dates
    event_date        = models.DateField()
    reported_at       = models.DateTimeField(auto_now_add=True)
    closed_at         = models.DateTimeField(null=True, blank=True)
    notes             = models.TextField(blank=True)

    class Meta:
        ordering = ['-reported_at']

    def save(self, *args, **kwargs):
        if not self.nc_number:
            from django.utils import timezone
            year = timezone.now().year
            last = NonConformance.objects.filter(nc_number__startswith=f'NC-{year}-').count()
            self.nc_number = f'NC-{year}-{last + 1:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nc_number}: {self.get_nc_type_display()} ({self.get_severity_display()})"


class CorrectiveAction(models.Model):
    """
    A single corrective or preventive action linked to a NonConformance.
    Multiple CAs per NC are typical.
    """
    ACTION_TYPES = [
        ('corrective',  'Corrective — fixes the specific instance'),
        ('preventive',  'Preventive — prevents recurrence system-wide'),
        ('systemic',    'Systemic — process / SOP change'),
    ]
    STATUS = [
        ('assigned',    'Assigned'),
        ('in_progress', 'In Progress'),
        ('completed',   'Completed — awaiting verification'),
        ('verified',    'Verified Effective'),
        ('ineffective', 'Verified — Ineffective (re-open NC)'),
    ]

    nc              = models.ForeignKey(NonConformance, on_delete=models.PROTECT, related_name='actions')
    action_type     = models.CharField(max_length=15, choices=ACTION_TYPES)
    status          = models.CharField(max_length=15, choices=STATUS, default='assigned')
    description     = models.TextField()
    assigned_to     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    due_date        = models.DateField()
    completed_at    = models.DateTimeField(null=True, blank=True)
    completed_by    = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    verified_at     = models.DateTimeField(null=True, blank=True)
    verified_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    verification_notes = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date']

    def is_overdue(self):
        from django.utils import timezone
        return self.status not in ('completed', 'verified', 'ineffective') and timezone.now().date() > self.due_date

    def __str__(self):
        return f"CA #{self.pk} ({self.nc.nc_number}): {self.description[:60]}"


class NewLotValidation(models.Model):
    """
    New reagent lot validation (parallel testing) before clinical release.

    AABB / ISO 15189 mandate that every incoming reagent lot is validated
    against the current in-use lot before being placed into service.
    Pass criteria: new lot reactivity must be ≥ existing lot on all test samples.

    Workflow:
      pending   → sampling complete → (reviewer signs off) → approved
      If the new lot fails any control: status → rejected; a NonConformance is raised.
    """
    STATUS = [
        ('pending',   'Pending — not yet tested'),
        ('in_review', 'Testing complete — awaiting review'),
        ('approved',  'Approved for clinical use'),
        ('rejected',  'Rejected — does not meet acceptance criteria'),
    ]

    new_lot         = models.OneToOneField(ReagentLot, on_delete=models.PROTECT,
                                           related_name='lot_validation')
    reference_lot   = models.ForeignKey(ReagentLot, null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+',
                                        help_text='Current in-use lot used for parallel comparison')
    branch          = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    status          = models.CharField(max_length=12, choices=STATUS, default='pending')
    initiated_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    initiated_at    = models.DateTimeField(auto_now_add=True)
    reviewed_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+')
    reviewed_at     = models.DateTimeField(null=True, blank=True)
    review_notes    = models.TextField(blank=True)
    esign           = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+')
    # Linked to the CAPA system if rejected
    nc              = models.ForeignKey(NonConformance, null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='lot_validations')

    def overall_result(self):
        results = self.validation_results.all()
        if not results.exists():
            return 'pending'
        if results.filter(passed=False).exists():
            return 'fail'
        return 'pass'

    def __str__(self):
        return f"Validation: {self.new_lot} — {self.get_status_display()}"


class LotValidationResult(models.Model):
    """
    One test sample comparison within a NewLotValidation.
    Each row records a single cell/sample tested against both lots simultaneously.
    """
    validation   = models.ForeignKey(NewLotValidation, on_delete=models.CASCADE, related_name='validation_results')
    sample_label = models.CharField(max_length=100, help_text='e.g. "Known A2 cell", "Group O neg control"')
    # Grades from the existing in-use lot (reference)
    ref_grade    = models.CharField(max_length=5, choices=REACTION_GRADES)
    # Grades from the new lot under test
    new_grade    = models.CharField(max_length=5, choices=REACTION_GRADES)
    passed       = models.BooleanField(default=True)
    comment      = models.CharField(max_length=200, blank=True)

    _GRADE_ORDER = ['0', 'w+', '1+', '2+', '3+', '4+', 'hem', 'mf']

    def save(self, *args, **kwargs):
        # Pass if new lot reacts at least as strongly as reference lot
        ref_idx = self._GRADE_ORDER.index(self.ref_grade) if self.ref_grade in self._GRADE_ORDER else 0
        new_idx = self._GRADE_ORDER.index(self.new_grade) if self.new_grade in self._GRADE_ORDER else 0
        self.passed = (new_idx >= ref_idx)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sample_label}: ref={self.ref_grade} new={self.new_grade} → {'PASS' if self.passed else 'FAIL'}"


# ─── SOP Management ───────────────────────────────────────────────────────────

SOP_CATEGORIES = [
    ('pre_transfusion',  'Pre-Transfusion Testing'),
    ('blood_grouping',   'Blood Grouping &amp; Antibody Screening'),
    ('crossmatch',       'Crossmatch Procedures'),
    ('component_prep',   'Component Preparation &amp; Processing'),
    ('cold_chain',       'Cold Chain &amp; Storage'),
    ('quality_control',  'Quality Control &amp; Reagent Management'),
    ('donor_screening',  'Donor Screening &amp; TTI Testing'),
    ('administration',   'Transfusion Administration'),
    ('emergency',        'Emergency &amp; MTP Procedures'),
    ('waste_disposal',   'Waste Disposal &amp; Spillage'),
    ('equipment',        'Equipment Maintenance &amp; Calibration'),
    ('other',            'Other'),
]


class StandardOperatingProcedure(models.Model):
    """
    Master SOP register — ISO 15189:2022 clause 7.4 requires a controlled
    document management system for all SOPs.  Each row is a procedure; version
    history is in SOPVersion.  Only one version is 'active' at any time.
    """
    STATUS = [
        ('draft',      'Draft — under authoring'),
        ('review',     'In Review — awaiting approval'),
        ('active',     'Active — approved for use'),
        ('superseded', 'Superseded — replaced by newer version'),
        ('retired',    'Retired — withdrawn from use'),
    ]

    sop_code     = models.CharField(max_length=30, unique=True,
                                    help_text='e.g. BB-SOP-001')
    title        = models.CharField(max_length=200)
    category     = models.CharField(max_length=25, choices=SOP_CATEGORIES)
    owner        = models.ForeignKey(settings.AUTH_USER_MODEL,
                                     on_delete=models.PROTECT, related_name='+',
                                     help_text='Procedure owner / responsible person')
    branch       = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    status       = models.CharField(max_length=12, choices=STATUS, default='draft')
    review_interval_months = models.SmallIntegerField(
        default=12,
        help_text='Months between mandatory periodic reviews (ISO 15189: at least annually)',
    )
    next_review_due = models.DateField(null=True, blank=True)
    # Soft-link to the active version — updated by approve_sop_version()
    active_version = models.ForeignKey(
        'SOPVersion', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    created_by   = models.ForeignKey(settings.AUTH_USER_MODEL,
                                     on_delete=models.PROTECT, related_name='+',
                                     related_query_name='sops_created')

    class Meta:
        ordering = ['sop_code']

    def is_overdue_review(self):
        from django.utils import timezone
        return self.next_review_due and timezone.now().date() > self.next_review_due

    def __str__(self):
        return f"{self.sop_code}: {self.title} ({self.get_status_display()})"


class SOPVersion(models.Model):
    """
    A single version of an SOP document.
    Immutable once approved — changes require a new version.
    """
    STATUS = [
        ('draft',    'Draft'),
        ('review',   'In Review'),
        ('approved', 'Approved'),
        ('retired',  'Retired'),
    ]

    sop          = models.ForeignKey(StandardOperatingProcedure,
                                     on_delete=models.PROTECT, related_name='versions')
    version_number = models.CharField(max_length=20, help_text='e.g. 1.0, 2.3')
    status       = models.CharField(max_length=10, choices=STATUS, default='draft')
    summary_of_changes = models.TextField(blank=True,
                                           help_text='What changed from the previous version')
    document_text = models.TextField(blank=True,
                                      help_text='Full SOP text (plain text or Markdown)')
    authored_by  = models.ForeignKey(settings.AUTH_USER_MODEL,
                                     on_delete=models.PROTECT, related_name='+')
    authored_at  = models.DateTimeField(auto_now_add=True)
    reviewed_by  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='+')
    reviewed_at  = models.DateTimeField(null=True, blank=True)
    approved_by  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='+')
    approved_at  = models.DateTimeField(null=True, blank=True)
    esign        = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='+')

    class Meta:
        ordering = ['-authored_at']
        unique_together = [('sop', 'version_number')]

    def __str__(self):
        return f"{self.sop.sop_code} v{self.version_number} ({self.get_status_display()})"


# ─── Internal Quality Audit ────────────────────────────────────────────────────

class InternalAudit(models.Model):
    """
    ISO 15189:2022 clause 8.7 — internal audits must be conducted at planned
    intervals to verify that the QMS conforms to requirements.  AABB 9th ed.
    also requires a formal internal audit program.
    """
    AUDIT_TYPES = [
        ('full_system',      'Full QMS System Audit'),
        ('process',          'Process Audit (specific procedure)'),
        ('follow_up',        'Follow-up Audit (verify CAPA effectiveness)'),
        ('unannounced',      'Unannounced Spot Audit'),
    ]
    STATUS = [
        ('scheduled',   'Scheduled'),
        ('in_progress', 'In Progress'),
        ('complete',    'Complete — findings issued'),
        ('closed',      'Closed — all findings resolved'),
    ]

    audit_number   = models.CharField(max_length=25, unique=True,
                                      help_text='Auto-assigned e.g. AUD-2026-001')
    audit_type     = models.CharField(max_length=20, choices=AUDIT_TYPES)
    scope          = models.TextField(help_text='What areas / processes will be audited')
    branch         = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    status         = models.CharField(max_length=15, choices=STATUS, default='scheduled')
    lead_auditor   = models.ForeignKey(settings.AUTH_USER_MODEL,
                                       on_delete=models.PROTECT, related_name='+')
    scheduled_date = models.DateField()
    start_date     = models.DateField(null=True, blank=True)
    end_date       = models.DateField(null=True, blank=True)
    # ISO 15189: auditor must be independent of area being audited
    auditee_area   = models.CharField(max_length=100, help_text='Department / area being audited')
    # CAPA raised if major findings
    nc             = models.ForeignKey(NonConformance, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='audits')
    closing_notes  = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    created_by     = models.ForeignKey(settings.AUTH_USER_MODEL,
                                       on_delete=models.PROTECT, related_name='+',
                                       related_query_name='audits_created')

    class Meta:
        ordering = ['-scheduled_date']

    def save(self, *args, **kwargs):
        if not self.audit_number:
            from django.utils import timezone
            year = timezone.now().year
            last = InternalAudit.objects.filter(audit_number__startswith=f'AUD-{year}-').count()
            self.audit_number = f'AUD-{year}-{last + 1:03d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.audit_number}: {self.get_audit_type_display()} @ {self.scheduled_date}"


class AuditFinding(models.Model):
    """
    Individual finding raised during an InternalAudit.
    Classified per ISO 15189: major / minor / observation.
    """
    CLASSIFICATION = [
        ('major',       'Major — direct impact on quality / safety'),
        ('minor',       'Minor — deviation with limited impact'),
        ('observation', 'Observation — opportunity for improvement'),
    ]
    STATUS = [
        ('open',     'Open'),
        ('capa',     'CAPA Raised'),
        ('resolved', 'Resolved'),
    ]

    audit          = models.ForeignKey(InternalAudit, on_delete=models.CASCADE, related_name='findings')
    reference      = models.CharField(max_length=30, blank=True,
                                      help_text='ISO clause or AABB standard cited e.g. ISO 15189:7.4.1')
    classification = models.CharField(max_length=15, choices=CLASSIFICATION)
    description    = models.TextField()
    status         = models.CharField(max_length=10, choices=STATUS, default='open')
    nc             = models.ForeignKey(NonConformance, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='audit_findings')
    due_date       = models.DateField(null=True, blank=True)
    resolved_at    = models.DateField(null=True, blank=True)
    resolution     = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['classification', '-created_at']

    def is_overdue(self):
        from django.utils import timezone
        return self.status not in ('resolved',) and self.due_date and timezone.now().date() > self.due_date

    def __str__(self):
        return f"{self.audit.audit_number} — {self.get_classification_display()}: {self.description[:60]}"


# ─── Staff Competency Assessment ──────────────────────────────────────────────

class StaffCompetency(models.Model):
    """
    ISO 15189:2022 clause 6.2 — Personnel competency records.

    Each row documents that a staff member has been assessed as competent
    to perform a specific task or use a specific procedure / instrument.

    Annual re-assessment is mandatory.  The system alerts when any active
    competency is approaching its reassessment due date.
    """
    TASK_CATEGORIES = [
        ('blood_grouping',    'Blood Grouping & Antibody Screening'),
        ('crossmatch',        'Crossmatch (Manual and Electronic)'),
        ('component_prep',    'Component Preparation'),
        ('reagent_qc',        'Reagent QC & Lot Release'),
        ('equipment',         'Equipment Operation & Calibration'),
        ('cold_chain',        'Cold Chain Monitoring'),
        ('phlebotomy',        'Phlebotomy / Sample Collection'),
        ('bedside_admin',     'Bedside Transfusion Administration'),
        ('emergency_release', 'Emergency / O-neg Release Protocol'),
        ('data_entry',        'LIS Data Entry & Record Management'),
        ('other',             'Other'),
    ]
    METHODS = [
        ('direct_observation', 'Direct Observation of Work'),
        ('review_records',     'Review of Recorded Results'),
        ('blind_sample',       'Blind Sample / Proficiency Test'),
        ('oral_exam',          'Oral Examination'),
        ('written_exam',       'Written Examination'),
        ('simulation',         'Simulation / Practical Assessment'),
    ]
    OUTCOMES = [
        ('competent',             'Competent — approved for independent practice'),
        ('competent_supervised',  'Competent Under Supervision Only'),
        ('not_yet_competent',     'Not Yet Competent — retraining required'),
        ('withdrawn',             'Withdrawn — competency revoked'),
    ]

    staff_member     = models.ForeignKey(settings.AUTH_USER_MODEL,
                                         on_delete=models.PROTECT, related_name='competencies')
    task_category    = models.CharField(max_length=25, choices=TASK_CATEGORIES)
    task_description = models.CharField(max_length=200,
                                        help_text='Specific task / SOP, e.g. "ABO Grouping by gel card (BB-SOP-001 v2.1)"')
    related_sop      = models.ForeignKey(StandardOperatingProcedure, null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name='competency_records')
    assessment_method = models.CharField(max_length=25, choices=METHODS)
    assessed_by      = models.ForeignKey(settings.AUTH_USER_MODEL,
                                         on_delete=models.PROTECT, related_name='+',
                                         help_text='Supervisor / assessor — must be different from staff_member')
    assessed_at      = models.DateTimeField()
    outcome          = models.CharField(max_length=25, choices=OUTCOMES)
    score            = models.SmallIntegerField(null=True, blank=True,
                                                help_text='Score if applicable (0–100)')
    pass_threshold   = models.SmallIntegerField(null=True, blank=True, default=80,
                                                help_text='Minimum score to pass')
    comments         = models.TextField(blank=True)
    # Annual reassessment
    reassessment_due = models.DateField(help_text='ISO 15189 requires at minimum annual re-assessment')
    branch           = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    esign            = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True,
                                         on_delete=models.PROTECT, related_name='+')
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-assessed_at']

    def is_overdue(self):
        from django.utils import timezone
        return timezone.now().date() > self.reassessment_due

    def __str__(self):
        return f"{self.staff_member.display_name or self.staff_member.username} — {self.task_category} ({self.get_outcome_display()})"


# ─── Transfusion Committee ─────────────────────────────────────────────────────

class TransfusionCommittee(models.Model):
    """
    Transfusion Committee (TC) meeting records.

    ISO 15189:2022 clause 8.8 + AABB Standards 9th ed 9.0 require
    a transfusion committee / governance group to:
    - Review QI metrics quarterly
    - Review serious adverse reactions and sentinel events
    - Approve new policies and transfusion guidelines
    - Track corrective actions to completion

    A quorum must be met (haematologist, transfusion practitioner, clinician representative).
    Minutes must be approved and filed as controlled documents.
    """
    MEETING_TYPES = [
        ('quarterly', 'Quarterly Clinical Governance Review'),
        ('annual',    'Annual Governance & Audit Review'),
        ('ad_hoc',    'Ad-Hoc / Special Meeting'),
    ]
    STATUSES = [
        ('planned',           'Planned'),
        ('held',              'Meeting Held — minutes pending'),
        ('minutes_draft',     'Minutes in Draft'),
        ('minutes_approved',  'Minutes Approved'),
    ]

    branch          = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='committee_meetings')
    meeting_type    = models.CharField(max_length=15, choices=MEETING_TYPES)
    scheduled_date  = models.DateField()
    actual_date     = models.DateField(null=True, blank=True)
    chair           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
                                        help_text='Meeting chair (typically senior haematologist or medical director)')
    attendees_text  = models.TextField(help_text='List of attendees — one per line: "Name, Role"')
    quorum_met      = models.BooleanField(default=True)
    status          = models.CharField(max_length=20, choices=STATUSES, default='planned')

    # QI indicators reviewed (references quality_indicator codes)
    qi_reviewed     = models.JSONField(default=list, blank=True,
                                       help_text='QI indicators reviewed, e.g. ["QI-1","QI-2"]')
    agenda_text     = models.TextField(blank=True, help_text='Meeting agenda items')
    minutes_text    = models.TextField(blank=True, help_text='Full meeting minutes')

    # Approval e-signature
    approved_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+')
    approved_at     = models.DateTimeField(null=True, blank=True)
    esign           = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+')

    created_by      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_date']

    def __str__(self):
        return f"TC Meeting {self.scheduled_date} ({self.get_meeting_type_display()}) @ {self.branch}"

    def open_actions_count(self):
        return self.actions.filter(status__in=('open', 'in_progress')).count()


class CommitteeAction(models.Model):
    """Action items arising from a transfusion committee meeting."""
    STATUSES = [
        ('open',        'Open'),
        ('in_progress', 'In Progress'),
        ('completed',   'Completed'),
        ('deferred',    'Deferred to Next Meeting'),
    ]

    meeting          = models.ForeignKey(TransfusionCommittee, on_delete=models.CASCADE, related_name='actions')
    description      = models.TextField()
    owner_name       = models.CharField(max_length=200, help_text='Responsible person (name + role)')
    owner            = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                         on_delete=models.PROTECT, related_name='+')
    due_date         = models.DateField()
    status           = models.CharField(max_length=15, choices=STATUSES, default='open')
    completion_notes = models.TextField(blank=True)
    completed_at     = models.DateField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date']

    def is_overdue(self):
        from django.utils import timezone
        return self.status in ('open', 'in_progress') and self.due_date < timezone.now().date()

    def __str__(self):
        return f"Action #{self.pk} [{self.meeting}]: {self.description[:60]}"
