from django.db import models
from django.conf import settings
from django.utils import timezone


class TestDefinition(models.Model):
    """Configurable list of required infectious disease tests."""
    test_code  = models.CharField(max_length=50, primary_key=True)
    name       = models.CharField(max_length=200)
    pathogen   = models.CharField(max_length=100, blank=True)
    method     = models.CharField(max_length=100, blank=True)  # ELISA, NAT, RPR...
    mandatory  = models.BooleanField(default=True)
    applies_to = models.CharField(
        max_length=10,
        choices=[('donors','Donors'),('patients','Patients'),('both','Both')],
        default='donors',
    )
    is_confirmatory = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.test_code} — {self.name}"


class Sample(models.Model):
    """A blood sample drawn from a patient (or donor) for testing."""
    TYPES = [
        ('pre_transfusion', 'Pre-Transfusion'),
        ('donor_screening', 'Donor Screening'),
        ('quality_control', 'Quality Control'),
        ('external', 'External'),
    ]
    ABO_CONFIRM = [
        ('confirmed', 'Confirmed (2 determinations)'),
        ('single_determination', 'Single Determination Only'),
        ('discrepant', 'Discrepant — Investigation Needed'),
        ('not_applicable', 'N/A'),
    ]

    patient  = models.ForeignKey('patients.Patient', null=True, blank=True, on_delete=models.PROTECT, related_name='samples')
    donor    = models.ForeignKey('donors.Donor', null=True, blank=True, on_delete=models.PROTECT, related_name='samples')
    accession_number = models.CharField(max_length=100, unique=True)
    collected_at     = models.DateTimeField()
    collected_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    sample_type      = models.CharField(max_length=20, choices=TYPES)
    # 3-day rule: if patient transfused/pregnant in past 3 months, sample valid 72h only
    validity_expiry  = models.DateTimeField(null=True, blank=True)
    abo_confirmation_status = models.CharField(max_length=25, choices=ABO_CONFIRM, default='not_applicable')
    branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self) -> bool:
        if self.validity_expiry and timezone.now() > self.validity_expiry:
            return False
        return True

    def __str__(self):
        subject = self.patient or self.donor
        return f"Sample {self.accession_number} ({self.sample_type}) — {subject}"


class DonationTestResult(models.Model):
    """
    TTI (infectious disease) test result for a donation.
    A reactive result must immediately quarantine all units from that donation.
    """
    RESULTS = [
        ('reactive', 'Reactive'),
        ('non_reactive', 'Non-Reactive'),
        ('indeterminate', 'Indeterminate'),
        ('invalid', 'Invalid'),
    ]

    donation    = models.ForeignKey('donors.Donation', on_delete=models.PROTECT, related_name='test_results')
    test        = models.ForeignKey(TestDefinition, on_delete=models.PROTECT, related_name='+')
    sample      = models.ForeignKey(Sample, on_delete=models.PROTECT, related_name='+')
    result      = models.CharField(max_length=15, choices=RESULTS)
    instrument  = models.CharField(max_length=100, blank=True)
    instrument_lot = models.CharField(max_length=100, blank=True)
    s_co_ratio  = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    performed_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reviewed_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    esign         = models.ForeignKey('audit.ElectronicSignature', on_delete=models.PROTECT, related_name='+')
    performed_at  = models.DateTimeField()

    class Meta:
        unique_together = [('donation', 'test')]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # If reactive: quarantine all units from this donation immediately
        if self.result == 'reactive':
            self._quarantine_donation_units()

    def _quarantine_donation_units(self):
        from inventory.models import BloodUnit
        from inventory.state_machine import transition_unit
        from accounts.models import User
        # Use the result performer as actor; fall back to any superuser
        actor = self.performed_by or User.objects.filter(is_superuser=True).first()
        if actor is None:
            return  # no valid actor — skip auto-quarantine, alert will fire via run_alerts
        units = BloodUnit.objects.filter(
            donation=self.donation,
            status__in=['quarantined', 'in_testing', 'available'],
        )
        for unit in units:
            try:
                transition_unit(
                    unit, 'failed_qc', actor,
                    reason=f"Reactive {self.test.test_code} result on donation #{self.donation_id}",
                )
            except Exception:
                pass  # already in a terminal/non-transitionable state

    def __str__(self):
        return f"{self.donation} / {self.test.test_code}: {self.result}"


class AntibodyScreen(models.Model):
    """Screens a patient sample for unexpected blood antibodies."""
    METHODS = [('IAT','IAT'),('PEG','PEG'),('LISS','LISS'),('gel','Gel'),('solid_phase','Solid Phase')]
    RESULTS = [('positive','Positive'),('negative','Negative'),('invalid','Invalid')]

    sample         = models.ForeignKey(Sample, on_delete=models.PROTECT, related_name='antibody_screens')
    method         = models.CharField(max_length=15, choices=METHODS)
    screen_cell_lot = models.CharField(max_length=100)
    result_per_cell = models.JSONField()        # {"cell_1": "neg", "cell_2": "pos", ...}
    overall_result  = models.CharField(max_length=10, choices=RESULTS)
    tech            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    performed_at    = models.DateTimeField()
    instrument      = models.CharField(max_length=100, blank=True)
    esign           = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return f"Screen on {self.sample.accession_number}: {self.overall_result}"


class AntibodyIdentification(models.Model):
    """Full panel to identify which specific antibody was found."""
    sample   = models.ForeignKey(Sample, on_delete=models.PROTECT, related_name='antibody_identifications')
    screen   = models.ForeignKey(AntibodyScreen, on_delete=models.PROTECT, related_name='+')
    panel_lot = models.CharField(max_length=100)
    identified_specificities = models.JSONField()   # ["anti-K", "anti-E"]
    excluded_specificities   = models.JSONField(default=list, blank=True)
    tech         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reviewed_by  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    performed_at = models.DateTimeField()
    esign        = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Write found antibodies to the patient's permanent history
        self._update_patient_antibody_history()

    def _update_patient_antibody_history(self):
        from patients.models import PatientAntibody
        patient = self.sample.patient
        if not patient:
            return
        for specificity in self.identified_specificities:
            PatientAntibody.objects.get_or_create(
                patient=patient,
                specificity=specificity,
                defaults={
                    'antigen_system': _guess_system(specificity),
                    'clinical_significance': 'significant',
                    'status': 'identified',
                    'first_identified_at': self.performed_at,
                    'first_identified_branch': self.sample.branch,
                    'identified_by': self.tech,
                    'sample': self.sample,
                }
            )

    def __str__(self):
        return f"ID panel on {self.sample.accession_number}: {self.identified_specificities}"


def _guess_system(specificity: str) -> str:
    """Map antibody name to antigen system — used as a default."""
    MAP = {
        'anti-D': 'Rh', 'anti-C': 'Rh', 'anti-c': 'Rh', 'anti-E': 'Rh', 'anti-e': 'Rh',
        'anti-K': 'Kell', 'anti-k': 'Kell',
        'anti-Fya': 'Duffy', 'anti-Fyb': 'Duffy',
        'anti-Jka': 'Kidd', 'anti-Jkb': 'Kidd',
        'anti-M': 'MNS', 'anti-N': 'MNS', 'anti-S': 'MNS', 'anti-s': 'MNS',
        'anti-Lea': 'Lewis', 'anti-Leb': 'Lewis',
    }
    return MAP.get(specificity, 'Unknown')


class NeonatalTransfusionOrder(models.Model):
    """
    Special order for neonatal/paediatric transfusion.

    AABB/BSH neonatal requirements:
    - ALL neonatal blood must be irradiated (prevent TA-GvHD)
    - CMV-negative (prevent CMV infection in immunocompromised neonate)
    - Leukoreduced
    - Volume calculated from weight: max 10-20 mL/kg per transfusion
    - Exchange transfusion: blood <5 days old, irradiated, CMV-neg, compatible with infant AND mother
    - HDN: blood lacks the offending antigen
    """
    INDICATIONS = [
        ('top_up',        'Top-up transfusion (anaemia of prematurity)'),
        ('exchange',      'Exchange transfusion (HDN, hyperbilirubinaemia)'),
        ('intrauterine',  'Intrauterine transfusion'),
        ('hdn_treatment', 'HDN — Haemolytic Disease of Newborn'),
        ('fnait',         'FNAIT — Foetal/Neonatal Alloimmune Thrombocytopenia'),
        ('surgical',      'Peri-operative'),
        ('other',         'Other'),
    ]

    patient             = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='neonatal_orders')
    blood_request       = models.OneToOneField('BloodRequest', on_delete=models.PROTECT, related_name='neonatal_order')
    gestational_age_weeks = models.SmallIntegerField(null=True, blank=True)
    postnatal_age_days  = models.SmallIntegerField()
    weight_kg           = models.DecimalField(max_digits=5, decimal_places=3)
    indication          = models.CharField(max_length=20, choices=INDICATIONS)

    # Maternal information — critical for exchange transfusion compatibility
    maternal_abo        = models.CharField(max_length=2, blank=True)
    maternal_rh_d       = models.CharField(max_length=10, blank=True)
    maternal_antibodies = models.JSONField(default=list, blank=True, help_text='e.g. ["anti-D", "anti-c"]')

    # Mandatory requirements (all default True for neonates per AABB)
    irradiation_required  = models.BooleanField(default=True)
    cmv_negative_required = models.BooleanField(default=True)
    leukoreduced_required = models.BooleanField(default=True)
    # Exchange transfusion: blood must be <5 days old
    max_unit_age_days   = models.SmallIntegerField(null=True, blank=True, help_text='Max unit age in days (exchange: 5)')

    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at  = models.DateTimeField(auto_now_add=True)
    notes       = models.TextField(blank=True)

    @property
    def max_volume_ml(self):
        """AABB recommendation: 10-20 mL/kg. Default 15 mL/kg for top-up, 160 mL/kg for exchange."""
        if self.indication == 'exchange':
            return float(self.weight_kg) * 160
        return float(self.weight_kg) * 15

    def unit_eligible(self, unit) -> tuple:
        """Returns (eligible: bool, reasons: list)."""
        from django.utils import timezone
        reasons = []
        if self.irradiation_required and not unit.is_irradiated:
            reasons.append("Unit is NOT irradiated — mandatory for neonatal transfusion.")
        if self.cmv_negative_required and not unit.is_cmv_negative:
            reasons.append("Unit is NOT CMV-negative — mandatory for neonatal transfusion.")
        if self.leukoreduced_required and not unit.is_leukoreduced:
            reasons.append("Unit is NOT leukoreduced — mandatory for neonatal transfusion.")
        if self.max_unit_age_days:
            age_days = (timezone.now() - unit.collection_datetime).days
            if age_days > self.max_unit_age_days:
                reasons.append(f"Unit is {age_days} days old — maximum {self.max_unit_age_days} days for this indication.")
        return len(reasons) == 0, reasons

    def __str__(self):
        return f"Neonatal Order #{self.pk}: {self.get_indication_display()} for Patient #{self.patient_id}"


class DonationBloodGrouping(models.Model):
    """
    Serological ABO/Rh D typing performed on a donation sample in the lab.

    International practice (AABB/BSH/WHO):
      — Every donation must be ABO + Rh D typed on the donation sample.
      — If donor has no confirmed group on file, first-time typing is a SINGLE determination.
      — Second concordant determination (often from a second sample or second test run)
        allows the result to be marked 'confirmed' and propagated to blood units.
      — The blood group is WRITTEN ONTO each blood unit derived from the donation,
        so crossmatch can subsequently run against it.

    We also write the confirmed group back to Donor.blood_group_abo / rh so future
    crossmatch pre-selection works immediately.
    """
    ABO_RESULTS = [('A','A'),('B','B'),('AB','AB'),('O','O')]
    RH_RESULTS  = [('pos','D Positive'),('neg','D Negative'),('weak_d','Weak D (Du)')]
    METHODS     = [
        ('tube',        'Tube method (manual)'),
        ('gel',         'Gel / column agglutination'),
        ('solid_phase', 'Solid phase red cell adherence'),
        ('automated',   'Automated analyser'),
    ]
    DETERMINATION_STATUS = [
        ('first',      'First determination only'),
        ('confirmed',  'Confirmed (≥2 concordant determinations)'),
        ('discrepant', 'Discrepant — requires investigation'),
    ]

    donation    = models.ForeignKey('donors.Donation', on_delete=models.PROTECT,
                                    related_name='blood_groupings')
    sample      = models.ForeignKey(Sample, on_delete=models.PROTECT, related_name='donation_groupings')

    # Forward grouping (cells + antisera)
    forward_a   = models.CharField(max_length=3, choices=[('pos','Pos'),('neg','Neg')], blank=True)
    forward_b   = models.CharField(max_length=3, choices=[('pos','Pos'),('neg','Neg')], blank=True)

    # Reverse grouping (serum + known cells) — A cells, B cells
    reverse_a_cells = models.CharField(max_length=3, choices=[('pos','Pos'),('neg','Neg')], blank=True)
    reverse_b_cells = models.CharField(max_length=3, choices=[('pos','Pos'),('neg','Neg')], blank=True)

    # Interpreted ABO group from forward+reverse
    abo_result  = models.CharField(max_length=2, choices=ABO_RESULTS)

    # Rh D typing
    rh_d_result = models.CharField(max_length=10, choices=RH_RESULTS)
    weak_d_test_done = models.BooleanField(default=False,
        help_text='Weak D (Du) test performed (required for apparent Rh D negative donors)')

    method      = models.CharField(max_length=20, choices=METHODS)
    reagent_lot = models.CharField(max_length=100, blank=True)
    instrument  = models.CharField(max_length=100, blank=True)

    determination_status = models.CharField(max_length=15, choices=DETERMINATION_STATUS,
                                             default='first')
    notes       = models.TextField(blank=True)

    performed_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reviewed_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.PROTECT, related_name='+')
    esign         = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True,
                                      on_delete=models.PROTECT, related_name='+')
    performed_at  = models.DateTimeField()
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-performed_at']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.determination_status in ('confirmed', 'first'):
            self._propagate_to_units()
            if self.determination_status == 'confirmed':
                self._update_donor_blood_group()

    def _propagate_to_units(self):
        """Write the typed ABO/Rh onto every blood unit from this donation."""
        from inventory.models import BloodUnit
        BloodUnit.objects.filter(donation=self.donation).update(
            abo_type=self.abo_result,
            rh_d_type=self.rh_d_result,
        )

    def _update_donor_blood_group(self):
        """
        On confirmed typing, update the Donor master record so future donations
        start with a known blood group and crossmatch pre-selection works.
        """
        donor = self.donation.donor
        donor.blood_group_abo = self.abo_result
        donor.blood_group_rh  = self.rh_d_result
        donor.save(update_fields=['blood_group_abo', 'blood_group_rh'])

    def __str__(self):
        return (f"Blood Grouping — Donation #{self.donation_id}: "
                f"{self.abo_result} {self.rh_d_result} ({self.determination_status})")


class MSBOS(models.Model):
    """Maximum Surgical Blood Order Schedule — how many units to prepare per procedure."""
    procedure_code = models.CharField(max_length=100)
    branch = models.ForeignKey('core.Branch', null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    order_type = models.CharField(
        max_length=20,
        choices=[('none','None'),('type_and_screen','Type & Screen'),('crossmatch','Crossmatch')],
    )
    units_count = models.SmallIntegerField(default=0)

    class Meta:
        unique_together = [('procedure_code', 'branch')]

    def __str__(self):
        return f"{self.procedure_code}: {self.order_type} × {self.units_count}"


class SurgicalBloodOrder(models.Model):
    """
    Pre-operative blood order linked to MSBOS lookup.

    Workflow:
      1. Surgeon creates order with procedure_code + scheduled date.
      2. System auto-looks up MSBOS → suggests order_type + units.
      3. Blood bank approves → creates BloodRequest(s) per component.
      4. On cancel, linked requests are cancelled.
    """
    STATUS = [
        ('pending',   'Pending — awaiting blood bank review'),
        ('approved',  'Approved — units reserved'),
        ('fulfilled', 'Fulfilled — units issued'),
        ('cancelled', 'Cancelled'),
    ]
    ORDER_TYPES = [
        ('none',            'None required'),
        ('type_and_screen', 'Type & Screen only'),
        ('crossmatch',      'Crossmatch + Reserve'),
    ]

    patient             = models.ForeignKey('patients.Patient', on_delete=models.PROTECT,
                                             related_name='surgical_blood_orders')
    branch              = models.ForeignKey('core.Branch', on_delete=models.PROTECT,
                                             related_name='surgical_blood_orders')
    procedure_code      = models.CharField(max_length=100,
                                           help_text='Matches MSBOS procedure_code for lookup')
    procedure_name      = models.CharField(max_length=200, blank=True)
    scheduled_datetime  = models.DateTimeField()
    surgeon             = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                             related_name='+')

    # MSBOS lookup result (auto-populated on save if MSBOS entry found)
    msbos_order_type    = models.CharField(max_length=20, choices=ORDER_TYPES, blank=True)
    msbos_units_suggested = models.SmallIntegerField(default=0)
    msbos_matched       = models.BooleanField(default=False)

    # Blood bank override (can differ from MSBOS suggestion)
    approved_order_type = models.CharField(max_length=20, choices=ORDER_TYPES, blank=True)
    approved_units      = models.SmallIntegerField(default=0)
    component_class     = models.CharField(
        max_length=5,
        choices=[('RBC','RBC'),('FFP','FFP'),('PLT','PLT'),('CRYO','CRYO')],
        default='RBC',
    )
    approved_by         = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.PROTECT, related_name='+')
    approved_at         = models.DateTimeField(null=True, blank=True)

    status              = models.CharField(max_length=15, choices=STATUS, default='pending')
    notes               = models.TextField(blank=True)
    created_by          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                             related_name='+')
    created_at          = models.DateTimeField(auto_now_add=True)

    # Linked blood request (created on approval)
    blood_request       = models.OneToOneField(
        'BloodRequest', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='surgical_order',
    )

    def _lookup_msbos(self):
        """Populate msbos_* fields from MSBOS table. Called on creation."""
        try:
            msbos = MSBOS.objects.filter(
                procedure_code__iexact=self.procedure_code,
            ).filter(
                models.Q(branch=self.branch) | models.Q(branch__isnull=True)
            ).order_by(models.F('branch').desc(nulls_last=True)).first()  # branch-specific before global
            if msbos:
                self.msbos_order_type     = msbos.order_type
                self.msbos_units_suggested = msbos.units_count
                self.msbos_matched        = True
                # Pre-fill approval suggestion
                if not self.approved_order_type:
                    self.approved_order_type = msbos.order_type
                if not self.approved_units:
                    self.approved_units = msbos.units_count
        except Exception:
            pass

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            self._lookup_msbos()
        super().save(*args, **kwargs)

    def __str__(self):
        return (f"SurgicalOrder #{self.pk}: {self.procedure_code} "
                f"— Patient #{self.patient_id} ({self.status})")


class BloodRequest(models.Model):
    URGENCY = [('routine','Routine'),('urgent','Urgent'),('emergency_mtp','Emergency / MTP')]
    OUTCOMES = [('fulfilled','Fulfilled'),('partial','Partial'),('unmet','Unmet'),('cancelled','Cancelled')]
    CLASSES = [('RBC','RBC'),('FFP','FFP'),('PLT','PLT'),('CRYO','CRYO'),('WB','WB'),('GRAN','GRAN')]

    patient    = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='blood_requests')
    branch     = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='blood_requests')
    requesting_physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    component_class = models.CharField(max_length=5, choices=CLASSES)
    units_requested = models.SmallIntegerField()
    units_crossmatched = models.SmallIntegerField(default=0)
    units_transfused   = models.SmallIntegerField(default=0)
    urgency     = models.CharField(max_length=15, choices=URGENCY, default='routine')
    is_neonatal = models.BooleanField(default=False,
        help_text='Neonatal patient (< 4 months) — enforces irradiated, CMV-safe, small-volume aliquot')
    neonatal_weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Patient weight in kg — used to calculate max allowable volume (20 mL/kg)')
    # Snapshot of patient special requirements at request time
    special_requirements_snapshot = models.JSONField(default=dict, blank=True)

    requested_ts           = models.DateTimeField(auto_now_add=True)
    crossmatch_started_ts  = models.DateTimeField(null=True, blank=True)
    crossmatch_completed_ts = models.DateTimeField(null=True, blank=True)
    issued_ts              = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=15, choices=OUTCOMES, default='unmet')

    ruleset_version = models.ForeignKey(
        'compliance.ComplianceRuleset', null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )

    def __str__(self):
        return f"Request #{self.pk}: {self.units_requested}× {self.component_class} for Patient #{self.patient_id} ({self.urgency})"


class Crossmatch(models.Model):
    METHODS = [
        ('immediate_spin', 'Immediate Spin'),
        ('AHG', 'AHG / Full Antiglobulin'),
        ('electronic', 'Electronic / Computer'),
    ]
    RESULTS = [
        ('compatible', 'Compatible'),
        ('incompatible', 'Incompatible'),
        ('electronic_release', 'Electronic Release'),
        ('invalid', 'Invalid'),
    ]

    sample      = models.ForeignKey(Sample, on_delete=models.PROTECT, related_name='crossmatches')
    blood_unit  = models.ForeignKey('inventory.BloodUnit', on_delete=models.PROTECT, related_name='crossmatches')
    request     = models.ForeignKey(BloodRequest, on_delete=models.PROTECT, related_name='crossmatches')
    method      = models.CharField(max_length=20, choices=METHODS)
    result      = models.CharField(max_length=20, choices=RESULTS)
    antibody_screen_result = models.CharField(
        max_length=10,
        choices=[('negative','Negative'),('positive','Positive')],
        blank=True,
    )
    reagent_lot   = models.CharField(max_length=100, blank=True)
    tech          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    verified_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    performed_at  = models.DateTimeField()
    # JSON snapshot of which electronic-XM eligibility criteria were checked
    electronic_eligibility_snapshot = models.JSONField(null=True, blank=True)
    esign         = models.ForeignKey('audit.ElectronicSignature', on_delete=models.PROTECT, related_name='+')

    def __str__(self):
        return f"XM: {self.blood_unit.did} × Patient #{self.request.patient_id} → {self.result}"


class IssueTransaction(models.Model):
    """The act of handing over a blood unit. Written inside a SELECT FOR UPDATE transaction."""
    blood_unit  = models.ForeignKey('inventory.BloodUnit', on_delete=models.PROTECT, related_name='issue_transactions')
    patient     = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='issue_transactions')
    request     = models.ForeignKey(BloodRequest, on_delete=models.PROTECT, related_name='issue_transactions')
    crossmatch  = models.ForeignKey(Crossmatch, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    emergency_release = models.ForeignKey(
        'EmergencyRelease', null=True, blank=True,
        on_delete=models.PROTECT, related_name='issue_transactions',
    )
    issued_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    issue_esign = models.ForeignKey('audit.ElectronicSignature', on_delete=models.PROTECT, related_name='+')
    issued_at   = models.DateTimeField()
    intended_branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    abo_check_passed = models.BooleanField()

    def __str__(self):
        return f"Issue: {self.blood_unit.did} → Patient #{self.patient_id} @ {self.issued_at:%Y-%m-%d %H:%M}"


class EmergencyRelease(models.Model):
    """Blood issued before crossmatch is complete — life-threatening emergencies only."""
    RETRO_STATUS = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('incompatible_found', 'Incompatible Found'),
    ]
    SIGNOFF_STATUS = [('pending','Pending'),('signed_off','Signed Off')]

    request   = models.ForeignKey(BloodRequest, on_delete=models.PROTECT, related_name='emergency_releases')
    patient   = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='+')
    units     = models.JSONField()           # list of blood_unit PKs released
    physician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    justification     = models.TextField()
    release_datetime  = models.DateTimeField(auto_now_add=True)
    release_esign     = models.ForeignKey('audit.ElectronicSignature', on_delete=models.PROTECT, related_name='+')
    retrospective_xm_status = models.CharField(max_length=25, choices=RETRO_STATUS, default='pending')
    signoff_status    = models.CharField(max_length=15, choices=SIGNOFF_STATUS, default='pending')
    signoff_physician = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    signoff_at    = models.DateTimeField(null=True, blank=True)
    signoff_esign = models.ForeignKey(
        'audit.ElectronicSignature', null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )

    def __str__(self):
        return f"Emergency release #{self.pk} for Patient #{self.patient_id} ({self.signoff_status})"


class TransfusionReaction(models.Model):
    """Record of an adverse transfusion event — every grade, every type."""
    IMPUTABILITY = [
        ('certain', 'Certain'), ('probable', 'Probable'), ('possible', 'Possible'),
        ('unlikely', 'Unlikely'), ('excluded', 'Excluded'),
    ]
    SEVERITY = [
        ('grade_1', 'Grade 1 — Mild'), ('grade_2', 'Grade 2 — Moderate'),
        ('grade_3', 'Grade 3 — Severe'), ('grade_4', 'Grade 4 — Life-threatening'),
        ('grade_5', 'Grade 5 — Fatal'),
    ]
    REACTION_TYPES = [
        ('AHTR', 'Acute Haemolytic (AHTR)'), ('DHTR', 'Delayed Haemolytic (DHTR)'),
        ('FNHTR', 'Febrile Non-Haemolytic (FNHTR)'), ('allergic_mild', 'Allergic — Mild'),
        ('allergic_severe', 'Allergic — Anaphylaxis'), ('TACO', 'TACO — Circulatory Overload'),
        ('TRALI', 'TRALI — Acute Lung Injury'), ('PTP', 'PTP — Post-transfusion Purpura'),
        ('TA_GvHD', 'TA-GvHD'), ('septic', 'Septic / Bacterial Contamination'),
        ('other', 'Other'),
    ]
    OUTCOMES = [
        ('full_recovery', 'Full Recovery'), ('ongoing', 'Ongoing'),
        ('sequelae', 'Permanent Sequelae'), ('death', 'Death'),
    ]

    issue_transaction = models.OneToOneField(
        IssueTransaction, on_delete=models.PROTECT, related_name='reaction',
    )
    patient     = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='reactions')
    blood_unit  = models.ForeignKey('inventory.BloodUnit', on_delete=models.PROTECT, related_name='+')
    reaction_type = models.CharField(max_length=20, choices=REACTION_TYPES)
    onset_datetime = models.DateTimeField()
    severity    = models.CharField(max_length=10, choices=SEVERITY)
    imputability = models.CharField(max_length=10, choices=IMPUTABILITY)
    outcome     = models.CharField(max_length=20, choices=OUTCOMES)
    clinical_description  = models.TextField()
    investigation_summary = models.TextField(blank=True)
    reported_to_authority = models.BooleanField(default=False)
    authority_report_ref  = models.CharField(max_length=100, blank=True)
    report_datetime       = models.DateTimeField(null=True, blank=True)
    recorded_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    recorded_at  = models.DateTimeField(auto_now_add=True)
    esign        = models.ForeignKey('audit.ElectronicSignature', on_delete=models.PROTECT, related_name='+')

    def __str__(self):
        return f"Reaction #{self.pk}: {self.get_reaction_type_display()} on {self.blood_unit.did}"


class TransfusionAdministration(models.Model):
    """Bedside administration record — documents the actual transfusion of a unit to a patient."""
    OUTCOMES = [
        ('completed', 'Completed — full volume given'),
        ('stopped_reaction', 'Stopped — Adverse Reaction'),
        ('stopped_patient', 'Stopped — Patient Request'),
        ('incomplete', 'Incomplete — clinical decision'),
    ]

    blood_unit    = models.ForeignKey('inventory.BloodUnit', on_delete=models.PROTECT, related_name='administrations')
    patient       = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='administrations')
    issue         = models.OneToOneField(IssueTransaction, on_delete=models.PROTECT, related_name='administration')
    bedside_verify_pass = models.BooleanField(default=False)
    patient_scan_id     = models.CharField(max_length=100, blank=True)
    unit_scan_did       = models.CharField(max_length=12, blank=True)
    admin_staff_1 = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    admin_staff_2 = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    start_at      = models.DateTimeField()
    completed_at  = models.DateTimeField(null=True, blank=True)
    volume_given_ml = models.SmallIntegerField(null=True, blank=True)
    outcome       = models.CharField(max_length=20, choices=OUTCOMES)
    vitals_json   = models.JSONField(null=True, blank=True)
    branch        = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    notes         = models.TextField(blank=True)
    esign         = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    created_at    = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Admin #{self.pk}: {self.blood_unit.did} → Patient #{self.patient_id}"


class MTPActivation(models.Model):
    """
    Massive Transfusion Protocol (MTP) activation record.

    MTP is activated in major haemorrhage (trauma, obstetric, surgical bleeding).
    Pre-defined packs (e.g. 6 RBC: 6 FFP: 1 PLT) are released without individual crossmatch.
    Per AABB/BSH: O-neg RBC + AB FFP + AB/O PLT while patient type is confirmed.
    Retrospective documentation and outcome review is mandatory.
    """
    STATUSES = [
        ('active',    'Active — ongoing haemorrhage'),
        ('stand_down','Stood Down — haemorrhage controlled'),
        ('completed', 'Completed — documentation done'),
    ]
    TRIGGER_TYPES = [
        ('trauma',       'Trauma'),
        ('obstetric',    'Obstetric haemorrhage (PPH)'),
        ('surgical',     'Surgical bleeding'),
        ('gi_bleed',     'GI Bleed'),
        ('haematology',  'Haematology (coagulopathy)'),
        ('other',        'Other'),
    ]

    patient         = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='mtp_activations')
    branch          = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='mtp_activations')
    trigger_type    = models.CharField(max_length=15, choices=TRIGGER_TYPES)
    activated_at    = models.DateTimeField()
    activated_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    stand_down_at   = models.DateTimeField(null=True, blank=True)
    status          = models.CharField(max_length=15, choices=STATUSES, default='active')

    # Pack composition issued during MTP (O-neg RBC used as universal)
    packs_issued    = models.SmallIntegerField(default=0, help_text='Number of MTP packs released')
    rbc_units_issued = models.SmallIntegerField(default=0)
    ffp_units_issued = models.SmallIntegerField(default=0)
    plt_units_issued = models.SmallIntegerField(default=0)
    cryo_units_issued = models.SmallIntegerField(default=0)

    # Outcome
    patient_survived = models.BooleanField(null=True, blank=True)
    retrospective_xm_completed = models.BooleanField(default=False,
        help_text='Retrospective crossmatch done after emergency (mandatory if patient survived)')
    reviewed_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+')
    clinical_notes  = models.TextField(blank=True)
    reported_to_haemovigilance = models.BooleanField(default=False)
    esign           = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+')
    created_at      = models.DateTimeField(auto_now_add=True)

    def duration_minutes(self):
        if self.stand_down_at and self.activated_at:
            return int((self.stand_down_at - self.activated_at).total_seconds() / 60)
        return None

    def __str__(self):
        return f"MTP #{self.pk} — {self.get_trigger_type_display()} — Patient #{self.patient_id} ({self.status})"


class TransfusionGuidelineCheck(models.Model):
    """
    Pre-transfusion clinical guideline compliance check (CDS).

    Records the clinical parameters and evaluates whether the transfusion
    meets WHO/AABB/BCSH guideline thresholds for each component type.
    Non-compliant requests can proceed with mandatory justification.
    """
    INDICATIONS = [
        ('anaemia',         'Symptomatic Anaemia'),
        ('acute_bleed',     'Acute Haemorrhage'),
        ('surgical',        'Peri-operative / Surgical'),
        ('mtp',             'Massive Transfusion Protocol (MTP)'),
        ('chemotherapy',    'Chemotherapy / Haematology'),
        ('icu',             'Critical Care / ICU'),
        ('obstetric',       'Obstetric (PPH / antepartum)'),
        ('neonatal',        'Neonatal / Paediatric'),
        ('cardiac',         'Cardiac Surgery / ECMO'),
        ('orthopaedic',     'Orthopaedic Surgery'),
        ('neurosurgery',    'Neurosurgery / Ophthalmology'),
        ('coagulopathy',    'Coagulopathy / DIC'),
        ('other',           'Other / Not Listed'),
    ]

    request                     = models.OneToOneField(
        BloodRequest, on_delete=models.PROTECT, related_name='guideline_check',
    )
    clinical_indication         = models.CharField(max_length=20, choices=INDICATIONS)
    is_actively_bleeding        = models.BooleanField(default=False)
    is_critical_care            = models.BooleanField(default=False)
    is_cardiac_surgery          = models.BooleanField(default=False)
    is_orthopaedic              = models.BooleanField(default=False)
    is_neurosurgery             = models.BooleanField(default=False)
    is_obstetric                = models.BooleanField(default=False)

    # Lab values at time of request — the CDS triggers
    pre_transfusion_hb_g_dl     = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True,
        help_text='Pre-transfusion haemoglobin in g/dL (required for RBC)',
    )
    pre_transfusion_plt_per_nl  = models.SmallIntegerField(
        null=True, blank=True,
        help_text='Pre-transfusion platelet count ×10⁹/L (required for PLT)',
    )
    pre_transfusion_fibrinogen_g_l = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True,
        help_text='Pre-transfusion fibrinogen in g/L (required for CRYO)',
    )
    pt_ratio                    = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True,
        help_text='PT as ratio of normal (e.g. 1.6 = 1.6× upper limit)',
    )
    aptt_ratio                  = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True,
        help_text='APTT as ratio of normal',
    )

    # CDS result — persisted as JSON so it can be re-displayed without re-running the engine
    meets_guideline             = models.BooleanField()
    guideline_flags_json        = models.JSONField(default=list)
    summary                     = models.TextField(blank=True)
    override_justification      = models.TextField(
        blank=True,
        help_text='Mandatory if transfusion does not meet guideline thresholds',
    )

    assessed_by                 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
    )
    assessed_at                 = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = 'Compliant' if self.meets_guideline else 'Non-compliant (justified)'
        return f"GuidelineCheck #{self.pk} — Request #{self.request_id} — {status}"


class LookbackCampaign(models.Model):
    """
    Initiated when a donor tests positive for a TTI marker (HIV, HBV, HCV, syphilis, etc.).
    Identifies all previous recipients of that donor's blood and tracks notification status.
    This is a regulatory requirement in most haemovigilance frameworks (SHOT, FDA 21 CFR 606).
    """
    STATUSES = [
        ('open',      'Open — recipients being identified'),
        ('notified',  'All recipients notified'),
        ('closed',    'Closed — investigation complete'),
    ]

    donor           = models.ForeignKey('donors.Donor', on_delete=models.PROTECT, related_name='lookback_campaigns')
    triggered_by_test = models.CharField(max_length=100, help_text='Test code that triggered this (e.g. HIV-1/2, HCV-Ab)')
    triggered_at    = models.DateTimeField()
    initiated_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    status          = models.CharField(max_length=10, choices=STATUSES, default='open')
    closed_at       = models.DateTimeField(null=True, blank=True)
    closed_by       = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    # Lookback window: all donations before this date are in scope
    lookback_from   = models.DateField(help_text='Earliest donation date in scope')
    notes           = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Lookback #{self.pk} — Donor #{self.donor_id} — {self.triggered_by_test}"


class LookbackNotification(models.Model):
    """One notification record per patient-recipient identified in a lookback campaign."""
    STATUSES = [
        ('pending',     'Pending'),
        ('notified',    'Notified — clinician informed'),
        ('tested',      'Patient tested — result pending'),
        ('result_neg',  'Patient tested — Negative'),
        ('result_pos',  'Patient tested — Positive (reported)'),
        ('deceased',    'Patient deceased — no notification possible'),
        ('untraceable', 'Patient untraceable'),
        ('waived',      'Notification waived — clinical decision'),
    ]

    campaign        = models.ForeignKey(LookbackCampaign, on_delete=models.CASCADE, related_name='notifications')
    patient         = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='lookback_notifications')
    issue_tx        = models.ForeignKey(IssueTransaction, on_delete=models.PROTECT, related_name='+',
                                        help_text='The original issue transaction for the suspect unit')
    unit_did        = models.CharField(max_length=12, help_text='DID of the potentially infectious unit')
    transfusion_date = models.DateField()
    status          = models.CharField(max_length=15, choices=STATUSES, default='pending')
    notified_at     = models.DateTimeField(null=True, blank=True)
    notified_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    clinician_name  = models.CharField(max_length=200, blank=True)
    notes           = models.TextField(blank=True)
    updated_at      = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"LB#{self.campaign_id} — Patient #{self.patient_id} — {self.status}"


class PostTransfusionOutcome(models.Model):
    """
    Records the post-transfusion Hb response, completing the PBM cycle.
    Should be documented 24–48 h after the final unit.
    Reference: AABB PBM Toolkit; NHS GIRFT Blood Programme 2021.
    """
    RESPONSES = [
        ('as_expected',    'As Expected (≥1 g/dL per unit RBC)'),
        ('above_expected', 'Above Expected'),
        ('below_expected', 'Below Expected — investigate'),
        ('deteriorated',   'Deteriorated — possible adverse event'),
    ]

    request    = models.OneToOneField(
        BloodRequest, on_delete=models.PROTECT, related_name='post_outcome',
    )
    patient    = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, related_name='post_outcomes',
    )
    post_hb_g_dl    = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True,
                                           help_text='Post-transfusion haemoglobin (g/dL)')
    post_hb_date    = models.DateField(null=True, blank=True)
    clinical_response = models.CharField(max_length=20, choices=RESPONSES, blank=True)
    further_transfusion_planned = models.BooleanField(default=False)
    reaction_occurred = models.BooleanField(default=False)
    notes           = models.TextField(blank=True)
    recorded_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    recorded_at     = models.DateTimeField(auto_now_add=True)

    def hb_increment(self):
        gc = getattr(self.request, 'guideline_check', None)
        if gc and gc.pre_transfusion_hb_g_dl and self.post_hb_g_dl:
            return round(float(self.post_hb_g_dl) - float(gc.pre_transfusion_hb_g_dl), 1)
        return None

    def expected_increment(self):
        units = self.request.units_transfused or 1
        return round(units * 1.0, 1)

    def __str__(self):
        return f"PostOutcome #{self.pk} — Request #{self.request_id}"


class ReactionInvestigation(models.Model):
    """
    Structured post-transfusion reaction workup.

    Covers SHOT/BSH requirements: DAT, repeat ABO, haemolysis markers,
    post-reaction serology, bacteriology, DIC screen, and final SHOT classification.
    """
    DAT_RESULTS = [
        ('positive', 'Positive'),
        ('weakly_positive', 'Weakly Positive'),
        ('negative', 'Negative'),
        ('not_done', 'Not Done'),
    ]
    HAEMOLYSIS = [
        ('absent', 'Absent'), ('mild', 'Mild (+)'),
        ('moderate', 'Moderate (++)'), ('severe', 'Severe (+++)'),
        ('not_done', 'Not Done'),
    ]
    SCREEN_RESULT = [
        ('negative', 'Negative'),
        ('positive_same', 'Positive — same specificity as before'),
        ('positive_new', 'Positive — new specificity identified'),
        ('not_done', 'Not Done'),
    ]
    CULTURE_RESULT = [
        ('negative', 'Negative'),
        ('positive', 'Positive — organism identified'),
        ('contaminated', 'Sample contaminated'),
        ('not_done', 'Not Done'),
    ]
    BLOOD_CULTURE = [
        ('negative', 'Negative'),
        ('positive', 'Positive — organism identified'),
        ('not_done', 'Not Done'),
    ]
    CONCLUSION = [
        ('confirmed_haemolytic', 'Confirmed Haemolytic Reaction'),
        ('confirmed_non_haemolytic', 'Confirmed Non-Haemolytic Reaction'),
        ('bacterial_contamination', 'Bacterial Contamination Confirmed'),
        ('no_abnormality', 'No Abnormality Detected'),
        ('inconclusive', 'Inconclusive'),
    ]
    SHOT_CATEGORIES = [
        ('AHTR',      'AHTR — Acute Haemolytic'),
        ('DHTR',      'DHTR — Delayed Haemolytic'),
        ('FNHTR',     'FNHTR — Febrile Non-Haemolytic'),
        ('allergic',  'Allergic / Anaphylactic'),
        ('TACO',      'TACO — Circulatory Overload'),
        ('TRALI',     'TRALI — Acute Lung Injury'),
        ('PTP',       'PTP — Post-Transfusion Purpura'),
        ('TA_GvHD',   'TA-GvHD'),
        ('IBCT',      'IBCT — Incorrect Blood Component Transfused'),
        ('HSE',       'HSE — Handling & Storage Error'),
        ('ATR',       'ATR — Adverse Transfusion Reaction (other)'),
        ('other',     'Other'),
        ('not_reportable', 'Not SHOT-Reportable'),
    ]

    reaction    = models.OneToOneField(TransfusionReaction, on_delete=models.PROTECT,
                                       related_name='investigation')
    started_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name='+')
    started_at  = models.DateTimeField(auto_now_add=True)

    # ── Repeat ABO check ──────────────────────────────────────────────────────
    repeat_abo_patient  = models.CharField(max_length=5, blank=True,
                                           help_text='Repeat ABO of patient post-reaction sample')
    repeat_abo_unit     = models.CharField(max_length=5, blank=True,
                                           help_text='Repeat ABO of unit segment / pilot tube')
    abo_discrepancy     = models.BooleanField(null=True, blank=True,
                                              help_text='Discrepancy between patient and unit ABO?')

    # ── Direct Antiglobulin Test ──────────────────────────────────────────────
    dat_result          = models.CharField(max_length=20, choices=DAT_RESULTS, default='not_done')
    dat_specificity     = models.CharField(max_length=100, blank=True,
                                           help_text='e.g. IgG, C3d, IgG+C3d')

    # ── Haemolysis markers ────────────────────────────────────────────────────
    plasma_haemoglobin  = models.CharField(max_length=10, choices=HAEMOLYSIS, default='not_done')
    urine_haemoglobin   = models.CharField(max_length=10, choices=HAEMOLYSIS, default='not_done')
    plasma_bilirubin_umol = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    plasma_ldh_iu       = models.IntegerField(null=True, blank=True,
                                              help_text='Lactate dehydrogenase (IU/L)')

    # ── Post-reaction serology ────────────────────────────────────────────────
    repeat_antibody_screen  = models.CharField(max_length=20, choices=SCREEN_RESULT, default='not_done')
    new_antibody_identified = models.CharField(max_length=100, blank=True,
                                               help_text='Specificity if newly identified')

    # ── Bacteriology ─────────────────────────────────────────────────────────
    unit_culture            = models.CharField(max_length=20, choices=CULTURE_RESULT, default='not_done')
    unit_culture_organism   = models.CharField(max_length=200, blank=True)
    patient_blood_culture   = models.CharField(max_length=20, choices=BLOOD_CULTURE, default='not_done')

    # ── DIC screen ────────────────────────────────────────────────────────────
    dic_screen_done         = models.BooleanField(default=False)
    dic_fibrinogen_g_l      = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    dic_pt_seconds          = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    dic_aptt_seconds        = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    dic_d_dimer             = models.CharField(max_length=30, blank=True,
                                               help_text='Qualitative or quantitative D-dimer')

    # ── Conclusion ────────────────────────────────────────────────────────────
    conclusion              = models.CharField(max_length=30, choices=CONCLUSION, blank=True)
    shot_category           = models.CharField(max_length=20, choices=SHOT_CATEGORIES, blank=True)
    shot_reportable         = models.BooleanField(default=False)
    narrative               = models.TextField(blank=True,
                                               help_text='Investigation narrative and final conclusions')

    completed_at    = models.DateTimeField(null=True, blank=True)
    completed_by    = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+')
    esign           = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='+')

    @property
    def is_complete(self):
        return self.completed_at is not None

    @property
    def haemolysis_positive(self):
        return (
            self.plasma_haemoglobin in ('mild', 'moderate', 'severe') or
            self.urine_haemoglobin  in ('mild', 'moderate', 'severe') or
            self.dat_result in ('positive', 'weakly_positive')
        )

    def __str__(self):
        return f"Investigation #{self.pk} — Reaction #{self.reaction_id}"
