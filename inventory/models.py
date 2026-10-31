from django.db import models
from django.conf import settings


COMPONENT_CLASSES = [
    ('RBC','Red Blood Cells'),
    ('FFP','Fresh Frozen Plasma'),
    ('PLT','Platelets'),
    ('CRYO','Cryoprecipitate'),
    ('WB','Whole Blood'),
    ('GRAN','Granulocytes'),
]

UNIT_STATUSES = [
    ('quarantined', 'Quarantined'),
    ('in_testing', 'In Testing'),
    ('available', 'Available'),
    ('failed_qc', 'Failed QC'),
    ('reserved', 'Reserved'),
    ('crossmatched', 'Crossmatched'),
    ('issued', 'Issued'),
    ('transfused', 'Transfused'),
    ('returned_to_stock', 'Returned to Stock'),
    ('wasted', 'Wasted'),
    ('expired', 'Expired'),
    ('recalled', 'Recalled'),
    ('quarantined_holdback', 'Quarantined — Hold Back'),
    ('transferred_out', 'Transferred Out'),
    ('in_transit', 'In Transit'),
    ('destroyed', 'Destroyed'),
]


class ComponentType(models.Model):
    """Our internal blood component catalog (no ISBT 128 license needed)."""
    code = models.CharField(max_length=20, primary_key=True)
    name = models.CharField(max_length=200)
    component_class = models.CharField(max_length=5, choices=COMPONENT_CLASSES)
    shelf_life_hours = models.SmallIntegerField()
    storage_temp_min_c = models.DecimalField(max_digits=4, decimal_places=1)
    storage_temp_max_c = models.DecimalField(max_digits=4, decimal_places=1)
    attributes = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.code} — {self.name}"


class BloodUnit(models.Model):
    # Core identity
    did = models.CharField(max_length=12, unique=True)   # immutable once set
    did_check_char = models.CharField(max_length=1)
    division_suffix = models.CharField(max_length=2, blank=True)

    donation = models.ForeignKey('donors.Donation', on_delete=models.PROTECT, related_name='units')
    component_type = models.ForeignKey(ComponentType, on_delete=models.PROTECT)
    component_class = models.CharField(max_length=5, choices=COMPONENT_CLASSES)

    # ABO/Rh confirmed for this specific unit at component preparation time
    abo_type = models.CharField(max_length=2, choices=[('A','A'),('B','B'),('AB','AB'),('O','O')], blank=True)
    rh_d_type = models.CharField(max_length=10, choices=[('pos','Positive'),('neg','Negative'),('weak_d','Weak D'),('unknown','Unknown')], blank=True)

    collection_datetime = models.DateTimeField()
    expiry_datetime = models.DateTimeField()
    volume_ml = models.SmallIntegerField(null=True, blank=True)
    additive_solution = models.CharField(max_length=50, blank=True)

    # State machine
    status = models.CharField(max_length=25, choices=UNIT_STATUSES, default='quarantined', db_index=True)
    version = models.IntegerField(default=1)  # increment on every status change

    # Ownership and reservation
    owner_branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='owned_units')
    reserved_for_request = models.ForeignKey(
        'transfusion.BloodRequest', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reserved_units',
    )
    reserved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    reserved_until = models.DateTimeField(null=True, blank=True)

    # Processing attributes
    is_leukoreduced  = models.BooleanField(default=False)
    is_irradiated    = models.BooleanField(default=False)
    irradiation_datetime = models.DateTimeField(null=True, blank=True)
    is_cmv_negative  = models.BooleanField(default=False)
    is_washed        = models.BooleanField(default=False)
    deglycerolized   = models.BooleanField(default=False)
    deglycerolization_datetime = models.DateTimeField(null=True, blank=True)
    pathogen_reduced = models.BooleanField(default=False)
    # e.g. {"K": true, "E": true} — antigen-negative for these specificities
    antigen_negative_set = models.JSONField(default=dict, blank=True)

    # Lineage
    parent_donation = models.ForeignKey(
        'donors.Donation', on_delete=models.PROTECT, related_name='derived_units',
    )
    production_event = models.ForeignKey(
        'ProcessingEvent', null=True, blank=True,
        on_delete=models.PROTECT, related_name='output_units',
    )

    # Separation of duties traceability
    collected_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    collected_at     = models.DateTimeField(null=True, blank=True)
    tested_by        = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    tested_at        = models.DateTimeField(null=True, blank=True)
    interpreted_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    interpreted_at   = models.DateTimeField(null=True, blank=True)
    released_by      = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    released_at      = models.DateTimeField(null=True, blank=True)

    # Physical storage location — nullable so legacy units without tracking still work
    storage_equipment = models.ForeignKey(
        'coldchain.StorageEquipment', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='stored_units',
    )

    # ISBT 128 upgrade path — leave null until ICCBBA registration obtained
    iccbba_fin          = models.CharField(max_length=13, blank=True)
    iccbba_product_code = models.CharField(max_length=8, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self) -> bool:
        from django.utils import timezone
        return self.expiry_datetime <= timezone.now()

    def satisfies_antigen_requirements(self, required_antigens: dict) -> bool:
        """
        Check if this unit is negative for all antigens the patient requires.
        required_antigens e.g. {"K": True, "E": True}
        """
        for antigen, required_negative in required_antigens.items():
            if required_negative and not self.antigen_negative_set.get(antigen):
                return False
        return True

    def __str__(self):
        return f"{self.did} [{self.component_class} / {self.status}]"


class ProcessingEvent(models.Model):
    TYPES = [
        ('whole_blood_separation', 'Whole Blood Separation'),
        ('apheresis_collection', 'Apheresis Collection'),
        ('split', 'Split'),
        ('irradiation', 'Irradiation'),
        ('leukoreduction', 'Leukoreduction'),
        ('pooling', 'Pooling'),
        ('wash', 'Wash'),
        ('aliquot', 'Aliquot'),
        ('thaw', 'Thaw'),
        ('pathogen_reduction', 'Pathogen Reduction'),
        ('deglycerolization', 'Deglycerolization'),
        ('freeze', 'Freeze'),
    ]

    event_type   = models.CharField(max_length=30, choices=TYPES)
    performed_at = models.DateTimeField()
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    branch       = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    blood_unit   = models.ForeignKey('BloodUnit', null=True, blank=True, on_delete=models.PROTECT, related_name='processing_events')
    sop_version  = models.CharField(max_length=50)
    esign        = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT)
    notes        = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_event_type_display()} by {self.performed_by} @ {self.performed_at:%Y-%m-%d %H:%M}"


class UnitLineage(models.Model):
    """
    One edge in the component family tree.
    Traverse with recursive queries to get full ancestor/descendant sets for recall.
    """
    RELATIONSHIPS = [
        ('derived_from', 'Derived From'),
        ('split_from', 'Split From'),
        ('pooled_into', 'Pooled Into'),
        ('aliquot_of', 'Aliquot Of'),
    ]

    processing_event  = models.ForeignKey(ProcessingEvent, on_delete=models.PROTECT, related_name='lineage_edges')
    parent_unit       = models.ForeignKey(BloodUnit, null=True, blank=True, on_delete=models.PROTECT, related_name='child_edges')
    parent_donation   = models.ForeignKey('donors.Donation', null=True, blank=True, on_delete=models.PROTECT, related_name='child_edges')
    child_unit        = models.ForeignKey(BloodUnit, on_delete=models.PROTECT, related_name='parent_edges')
    relationship      = models.CharField(max_length=20, choices=RELATIONSHIPS)

    def __str__(self):
        parent = self.parent_unit or f"Donation#{self.parent_donation_id}"
        return f"{parent} → {self.child_unit} ({self.relationship})"


class UnitStateTransition(models.Model):
    """
    The allowed moves in the state machine.
    Both the app and the issue logic consult this before changing status.
    """
    from_status        = models.CharField(max_length=25)
    to_status          = models.CharField(max_length=25)
    requires_permission = models.CharField(max_length=100, blank=True)
    guard_rule         = models.CharField(max_length=500, blank=True)

    class Meta:
        unique_together = [('from_status', 'to_status')]

    def __str__(self):
        return f"{self.from_status} → {self.to_status}"


class UnitStatusEvent(models.Model):
    """Append-only history of every status change a unit has gone through."""
    unit        = models.ForeignKey(BloodUnit, on_delete=models.PROTECT, related_name='status_events')
    from_status = models.CharField(max_length=25)
    to_status   = models.CharField(max_length=25)
    reason      = models.CharField(max_length=500, blank=True)
    actor       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    esign       = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ['occurred_at']

    def __str__(self):
        return f"{self.unit.did}: {self.from_status} → {self.to_status} @ {self.occurred_at:%Y-%m-%d %H:%M}"


class WastageRecord(models.Model):
    """
    Structured reason tracking for blood unit wastage/discard events.

    WHO / ISBT / SHOT all require wastage reason to be categorised for
    quality improvement. This feeds the analytics wastage reports.
    """
    REASONS = [
        ('expired_unused',        'Expired — unused (not issued)'),
        ('expired_issued',        'Expired — issued but not transfused'),
        ('unit_returned_late',    'Unit returned — exceeded 30-min rule'),
        ('temperature_excursion', 'Temperature excursion during storage'),
        ('temperature_transport', 'Temperature excursion during transport'),
        ('tti_reactive',          'TTI reactive result post-release'),
        ('failed_qc_processing',  'Failed QC — processing / component defect'),
        ('failed_qc_appearance',  'Failed QC — visual inspection (clots, haemolysis)'),
        ('recall',                'Recalled — donor lookback'),
        ('ordering_error',        'Ordering error — wrong component requested'),
        ('clinical_cancelled',    'Clinical decision — transfusion cancelled'),
        ('satellite_expired',     'Expired at satellite/ward'),
        ('tech_error',            'Technical/labelling error'),
        ('other',                 'Other (see notes)'),
    ]

    blood_unit      = models.ForeignKey(BloodUnit, on_delete=models.PROTECT, related_name='wastage_records')
    reason_code     = models.CharField(max_length=30, choices=REASONS)
    final_status    = models.CharField(max_length=25, choices=UNIT_STATUSES)
    notes           = models.TextField(blank=True)
    avoidable       = models.BooleanField(
        null=True, blank=True,
        help_text='Was this wastage preventable?',
    )
    value_gbp       = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Estimated cost in GBP (for financial reporting)',
    )
    recorded_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
    )
    branch          = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    recorded_at     = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Wastage {self.blood_unit.did}: {self.get_reason_code_display()}"


class LabelTemplate(models.Model):
    SYMBOLOGIES = [('Code128','Code 128'),('Codabar','Codabar')]

    version          = models.CharField(max_length=20)
    component_class  = models.CharField(max_length=5, choices=COMPONENT_CLASSES, blank=True)
    barcode_symbology = models.CharField(max_length=10, choices=SYMBOLOGIES, default='Code128')
    fields_config    = models.JSONField()         # which fields to print and where
    content_checksum = models.CharField(max_length=64)
    approved_by      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    approved_at      = models.DateTimeField()
    active           = models.BooleanField(default=True)

    def __str__(self):
        return f"Label template v{self.version} ({self.component_class or 'all'})"


class LabelPrintLog(models.Model):
    """Every label printed is recorded here."""
    blood_unit    = models.ForeignKey(BloodUnit, on_delete=models.PROTECT, related_name='label_prints')
    template      = models.ForeignKey(LabelTemplate, on_delete=models.PROTECT, related_name='+')
    did           = models.CharField(max_length=12)
    printed_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    printed_at    = models.DateTimeField(auto_now_add=True)
    printer_id    = models.CharField(max_length=100, blank=True)
    print_success = models.BooleanField(default=True)

    def __str__(self):
        return f"Label for {self.did} printed @ {self.printed_at:%Y-%m-%d %H:%M}"


class Transfer(models.Model):
    STATUSES = [
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('in_transit', 'In Transit'),
        ('received', 'Received'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    blood_unit      = models.ForeignKey(BloodUnit, on_delete=models.PROTECT, related_name='transfers')
    from_branch     = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='transfers_out')
    to_branch       = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='transfers_in')
    initiated_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    initiated_at    = models.DateTimeField(auto_now_add=True)
    approved_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    approved_at     = models.DateTimeField(null=True, blank=True)
    dispatched_at   = models.DateTimeField(null=True, blank=True)
    received_at     = models.DateTimeField(null=True, blank=True)
    received_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    status          = models.CharField(max_length=15, choices=STATUSES, default='requested')
    reason          = models.CharField(max_length=500, blank=True)
    cold_chain_ok   = models.BooleanField(null=True, blank=True)

    def __str__(self):
        return f"Transfer {self.blood_unit.did}: {self.from_branch} → {self.to_branch} ({self.status})"
