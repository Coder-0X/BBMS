from django.db import models
from django.conf import settings
import uuid


ABO_CHOICES = [('A','A'),('B','B'),('AB','AB'),('O','O')]
RH_CHOICES  = [('pos','Positive'),('neg','Negative'),('weak_d','Weak D'),('unknown','Unknown')]


class Patient(models.Model):
    """
    A persistent patient record — not a name on a request form.
    All blood history follows this record across visits and branches.
    """
    mpi_uid = models.UUIDField(default=uuid.uuid4, unique=True)  # master patient index

    # PII lives in privacy.SubjectIdentity
    subject = models.OneToOneField(
        'privacy.SubjectIdentity',
        on_delete=models.PROTECT,
        related_name='patient',
    )
    sex = models.CharField(max_length=10, choices=[('M','Male'),('F','Female'),('U','Unknown')])
    dob = models.DateField(null=True, blank=True)

    # Declared at registration — used as fallback when no lab-confirmed blood group exists yet
    abo = models.CharField(max_length=2, choices=ABO_CHOICES, blank=True)
    rh_d = models.CharField(max_length=10, choices=RH_CHOICES, blank=True)

    # If duplicate records were merged, point to the surviving record
    merged_into = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.PROTECT, related_name='merged_from',
    )
    record_status = models.CharField(
        max_length=10,
        choices=[('active','Active'),('merged','Merged'),('blocked','Blocked')],
        default='active',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')

    def current_blood_group(self):
        """Returns the latest confirmed ABO/Rh, or None."""
        return self.blood_groups.filter(is_discrepant=False).order_by('-determined_at').first()

    def effective_blood_group(self):
        """
        Returns the best available blood group info.
        Prefers lab-confirmed PatientBloodGroup; falls back to the declared
        abo/rh_d fields set at registration if no lab record exists yet.
        Returns None when neither is available.
        """
        bg = self.current_blood_group()
        if bg:
            return bg
        if self.abo:
            from types import SimpleNamespace
            return SimpleNamespace(
                abo=self.abo,
                rh_d=self.rh_d or 'unknown',
                is_discrepant=False,
                method='declared',
                source='declared',
            )
        return None

    def active_antibodies(self):
        """Returns all clinically significant antibodies — even evanescent ones."""
        return self.antibodies.filter(
            clinical_significance='significant',
            status__in=['identified', 'historical_only'],
        )

    def active_special_requirements(self):
        return self.special_requirements.filter(active=True)

    def __str__(self):
        return f"Patient #{self.pk} (MPI: {str(self.mpi_uid)[:8]}…)"


class PatientIdentifier(models.Model):
    """
    All the different IDs a patient might have across branches.
    E.g. MRN at branch A, MRN at branch B, national ID — all pointing to one Patient.
    """
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='identifiers')
    system  = models.CharField(max_length=100)   # e.g. 'MRN:BranchA', 'national-id'
    value   = models.CharField(max_length=200)
    is_primary = models.BooleanField(default=False)

    class Meta:
        unique_together = [('system', 'value')]

    def __str__(self):
        return f"{self.system}: {self.value} → Patient #{self.patient_id}"


class PatientBloodGroup(models.Model):
    """
    Append-only. Every time a patient's blood group is tested, a new row is added.
    Never update — the history is the source of truth.
    The current blood group is a query over this table (Patient.current_blood_group()).
    """
    patient     = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='blood_groups')
    abo         = models.CharField(max_length=2, choices=ABO_CHOICES)
    rh_d        = models.CharField(max_length=10, choices=RH_CHOICES)
    method      = models.CharField(max_length=50)   # gel, tube, analyzer
    sample      = models.ForeignKey('transfusion.Sample', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    determined_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    # Second person confirms — required before first-ever group-specific issue
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    branch      = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    source      = models.CharField(
        max_length=20,
        choices=[('current_testing','Current Testing'),('historical','Historical'),('external','External')],
    )
    # True if this result conflicts with a prior determination → blocks electronic crossmatch
    is_discrepant = models.BooleanField(default=False)
    supersedes    = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    determined_at = models.DateTimeField()
    esign         = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return f"Patient #{self.patient_id}: {self.abo} {self.rh_d} @ {self.determined_at:%Y-%m-%d}"


class PatientAntibody(models.Model):
    """
    Lifelong antibody history. Append-only — never delete, never deactivate.
    Even if the antibody becomes undetectable on the current screen,
    it stays here and forces antigen-negative blood selection forever.
    """
    SIGNIFICANCE = [('significant','Significant'),('insignificant','Insignificant'),('unknown','Unknown')]
    STATUSES = [
        ('identified','Identified'),
        ('suspected','Suspected'),
        ('historical_only','Historical Only (evanescent)'),
        ('ruled_out','Ruled Out'),
    ]

    patient   = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='antibodies')
    # e.g. 'anti-K', 'anti-Jka', 'anti-E', 'anti-D'
    specificity    = models.CharField(max_length=50)
    antigen_system = models.CharField(max_length=50)  # Kell, Kidd, Duffy, Rh, MNS...
    clinical_significance = models.CharField(max_length=15, choices=SIGNIFICANCE)
    status    = models.CharField(max_length=20, choices=STATUSES)
    # True = antibody can disappear from screen but is still clinically dangerous
    evanescent = models.BooleanField(default=True)
    autocontrol_positive = models.BooleanField(default=False)

    first_identified_at     = models.DateTimeField()
    first_identified_branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    identified_by           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    last_demonstrated_at    = models.DateTimeField(null=True, blank=True)
    sample = models.ForeignKey('transfusion.Sample', null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return f"Patient #{self.patient_id}: {self.specificity} ({self.get_status_display()})"


class TransfusionConsent(models.Model):
    """
    Informed consent record for transfusion.
    Must be obtained before routine transfusion.
    Emergency transfusion may proceed without consent with mandatory retrospective documentation.
    Legal basis: common law, NHS consent guidelines, Joint Commission standards.
    """
    CONSENT_TYPES = [
        ('written',   'Written — signed consent form'),
        ('verbal',    'Verbal — witnessed'),
        ('implied',   'Implied — patient unable to consent (emergency)'),
        ('parent_guardian', 'Parent/Guardian (minor or incapacitated)'),
    ]
    STATUSES = [
        ('active',   'Active'),
        ('withdrawn', 'Withdrawn by patient'),
        ('expired',  'Expired (>30 days)'),
    ]

    patient         = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='consents')
    consent_type    = models.CharField(max_length=20, choices=CONSENT_TYPES)
    status          = models.CharField(max_length=10, choices=STATUSES, default='active')
    # Information provided: alternatives discussed, risks explained
    alternatives_discussed = models.BooleanField(default=False)
    risks_explained        = models.BooleanField(default=False)
    questions_answered     = models.BooleanField(default=False)
    obtained_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    obtained_at     = models.DateTimeField()
    # For written consent: reference to the physical form
    form_reference  = models.CharField(max_length=100, blank=True)
    # For implied/emergency: mandatory justification
    emergency_justification = models.TextField(blank=True)
    # Valid for 30 days from obtaining
    valid_until     = models.DateField(null=True, blank=True)
    withdrawn_at    = models.DateTimeField(null=True, blank=True)
    withdrawn_by    = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    branch          = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    notes           = models.TextField(blank=True)
    esign           = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    created_at      = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        from django.utils import timezone
        if self.status != 'active':
            return False
        if self.valid_until and timezone.now().date() > self.valid_until:
            return False
        return True

    def __str__(self):
        return f"Consent #{self.pk}: Patient #{self.patient_id} ({self.consent_type}, {self.status})"


class PatientTransfusionRequirement(models.Model):
    """Standing requirements for a patient — e.g. irradiated for life post-HSCT."""
    REQUIREMENTS = [
        ('irradiated',       'Irradiated Blood'),
        ('cmv_negative',     'CMV-Negative Blood'),
        ('washed',           'Washed Components'),
        ('antigen_negative', 'Antigen-Negative Blood'),
        ('phenotype_matched','Phenotype Matched'),
        ('leukoreduced_only','Leukoreduced Only'),
    ]

    patient     = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='special_requirements')
    requirement = models.CharField(max_length=20, choices=REQUIREMENTS)
    # For antigen_negative: which antigen, e.g. 'K'
    antigen_spec = models.CharField(max_length=100, blank=True)
    active      = models.BooleanField(default=True)
    reason      = models.CharField(max_length=500)
    set_by      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    set_at      = models.DateTimeField(auto_now_add=True)
    revoked_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    revoked_at  = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Patient #{self.patient_id}: {self.get_requirement_display()} ({'active' if self.active else 'revoked'})"


class BloodGroupDiscrepancyInvestigation(models.Model):
    """
    Formal investigation record when a new blood group result (PatientBloodGroup)
    conflicts with a previously confirmed result (is_discrepant=True).

    BCSH 2012 / SHOT guidance — all discrepancies must be investigated to root cause
    before the patient's group can be re-confirmed and electronic crossmatch re-enabled.
    """
    STATUS_CHOICES = [
        ('open',       'Open — under investigation'),
        ('resolved',   'Resolved — root cause identified'),
        ('escalated',  'Escalated — requires senior review / SHOT report'),
    ]
    ROOT_CAUSE_CHOICES = [
        ('clerical_sample',    'Clerical error — wrong sample label'),
        ('clerical_request',   'Clerical error — patient ID mismatch on request form'),
        ('technical_reagent',  'Technical error — reagent failure or deterioration'),
        ('technical_technique','Technical error — procedural / technique issue'),
        ('wbc_interference',   'Interference — WBC, rouleaux, cold agglutinin, DSTR'),
        ('recent_transfusion', 'Recent transfusion — mixed-field from allogeneic RBC'),
        ('hsct',               'Post-HSCT — donor chimaerism / engraftment'),
        ('genuine_change',     'Genuine phenotypic change (rare, document fully)'),
        ('patient_misid',      'Patient misidentification — WBIT event'),
        ('other',              'Other — see notes'),
    ]

    patient            = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='discrepancy_investigations')
    discrepant_group   = models.ForeignKey(
        PatientBloodGroup, on_delete=models.PROTECT,
        related_name='investigation_as_discrepant',
        help_text="The new result flagged is_discrepant=True",
    )
    prior_group        = models.ForeignKey(
        PatientBloodGroup, on_delete=models.PROTECT, null=True, blank=True,
        related_name='investigation_as_prior',
        help_text="The previously confirmed result that conflicts",
    )
    status             = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    root_cause         = models.CharField(max_length=30, choices=ROOT_CAUSE_CHOICES, blank=True)
    resolution_action  = models.TextField(blank=True, help_text="What was done to resolve — repeat sample, re-type, repeat request, etc.")
    confirmed_group    = models.ForeignKey(
        PatientBloodGroup, on_delete=models.PROTECT, null=True, blank=True,
        related_name='investigation_as_confirmed',
        help_text="The authoritative group after investigation (clears the discrepancy)",
    )
    shot_reportable    = models.BooleanField(default=False, help_text="Must be reported to SHOT / haemovigilance")
    wbit_event         = models.BooleanField(default=False, help_text="Wrong blood in tube — serious incident")
    notes              = models.TextField(blank=True)
    investigated_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
    )
    resolved_by        = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    branch             = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    esign              = models.ForeignKey(
        'audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    opened_at          = models.DateTimeField(auto_now_add=True)
    resolved_at        = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-opened_at']

    def __str__(self):
        return f"Discrepancy #{self.pk}: Patient #{self.patient_id} ({self.get_status_display()})"


class PatientPhenotype(models.Model):
    """
    Extended red cell antigen phenotype for a patient.

    Identical antigen panel to DonorPhenotype. Recorded BEFORE the first
    transfusion so that:
      1. Rh and Kell matched units can be selected (prevents alloimmunisation)
      2. If the patient forms antibodies, antigen-negative matching is guided
         by the patient's own phenotype (not just the donor's negative set)
      3. Supports full patient phenotype + antibody compatibility matrix

    BCSH 2016: All chronic transfusion patients and women of childbearing
    potential should be extended-phenotyped (Rh C/c/E/e, Kell) before
    first transfusion where possible.

    True = antigen present, False = antigen absent, None = not tested.
    """
    METHODS = [('serology', 'Serology (tube/gel)'), ('molecular', 'Molecular genotyping')]

    patient   = models.OneToOneField(Patient, on_delete=models.PROTECT, related_name='phenotype')
    typed_at  = models.DateTimeField()
    typed_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    method    = models.CharField(max_length=15, choices=METHODS, default='serology')
    branch    = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')

    # Rh (D is in PatientBloodGroup.rh_d)
    C   = models.BooleanField(null=True, blank=True)
    c   = models.BooleanField(null=True, blank=True)
    E   = models.BooleanField(null=True, blank=True)
    e   = models.BooleanField(null=True, blank=True)
    # Kell
    K   = models.BooleanField(null=True, blank=True)
    k   = models.BooleanField(null=True, blank=True)
    # Duffy
    Fya = models.BooleanField(null=True, blank=True)
    Fyb = models.BooleanField(null=True, blank=True)
    # Kidd
    Jka = models.BooleanField(null=True, blank=True)
    Jkb = models.BooleanField(null=True, blank=True)
    # MNS
    M   = models.BooleanField(null=True, blank=True)
    N   = models.BooleanField(null=True, blank=True)
    S   = models.BooleanField(null=True, blank=True)
    s   = models.BooleanField(null=True, blank=True)
    # Lewis
    Lea = models.BooleanField(null=True, blank=True)
    Leb = models.BooleanField(null=True, blank=True)
    # P1PK
    P1  = models.BooleanField(null=True, blank=True)

    notes      = models.TextField(blank=True)
    esign      = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    ANTIGEN_FIELDS = ['C','c','E','e','K','k','Fya','Fyb','Jka','Jkb','M','N','S','s','Lea','Leb','P1']
    ANTIGEN_SYSTEMS = {
        'Rh':   ['C','c','E','e'],
        'Kell': ['K','k'],
        'Duffy':['Fya','Fyb'],
        'Kidd': ['Jka','Jkb'],
        'MNS':  ['M','N','S','s'],
        'Lewis':['Lea','Leb'],
        'P1PK': ['P1'],
    }

    def antigen_present_set(self) -> list:
        """Antigens this patient HAS — cannot form antibodies to these."""
        return [a for a in self.ANTIGEN_FIELDS if getattr(self, a) is True]

    def antigen_absent_set(self) -> list:
        """Antigens this patient LACKS — AT RISK of forming antibodies if exposed."""
        return [a for a in self.ANTIGEN_FIELDS if getattr(self, a) is False]

    def required_negative_antigens(self) -> list:
        """
        For a patient with alloantibodies AND known phenotype,
        returns the antigens the transfused unit must be negative for.
        (antigens absent in patient → patient is at risk → unit must match)
        """
        from patients.models import PatientAntibody
        antibodies = PatientAntibody.objects.filter(
            patient=self.patient,
            clinical_significance='significant',
            status__in=['identified', 'historical_only'],
        )
        absent = set(self.antigen_absent_set())
        # Return antigens that are absent AND have an antibody
        ANTIBODY_TO_ANTIGEN = {
            'anti-C': 'C', 'anti-c': 'c', 'anti-E': 'E', 'anti-e': 'e',
            'anti-K': 'K', 'anti-k': 'k',
            'anti-Fya': 'Fya', 'anti-Fyb': 'Fyb',
            'anti-Jka': 'Jka', 'anti-Jkb': 'Jkb',
            'anti-M': 'M', 'anti-N': 'N', 'anti-S': 'S', 'anti-s': 's',
            'anti-Lea': 'Lea', 'anti-Leb': 'Leb',
        }
        result = []
        for ab in antibodies:
            antigen = ANTIBODY_TO_ANTIGEN.get(ab.specificity)
            if antigen and antigen in absent:
                result.append(antigen)
        return result

    def __str__(self):
        typed = sum(1 for a in self.ANTIGEN_FIELDS if getattr(self, a) is not None)
        return f"Phenotype Patient #{self.patient_id}: {typed}/{len(self.ANTIGEN_FIELDS)} antigens typed"


# ─── Therapeutic Phlebotomy ────────────────────────────────────────────────────

class TherapeuticPhlebotomy(models.Model):
    """
    Controlled therapeutic venesection for patients with iron overload or
    erythrocytosis.  NOT a donation — collected under medical order.

    Indications: hereditary haemochromatosis (HFE), polycythaemia vera,
    secondary erythrocytosis, porphyria cutanea tarda, haemosiderosis.

    BCSH 2008 / BSH Polycythaemia Guidelines: regular schedule to target
    Hb < 130 g/L (women) / < 150 g/L (men) or ferritin < 50 µg/L.
    """
    INDICATIONS = [
        ('haemochromatosis',     'Hereditary Haemochromatosis (HFE)'),
        ('polycythaemia_vera',   'Polycythaemia Vera'),
        ('secondary_eryth',      'Secondary Erythrocytosis'),
        ('haemosiderosis',       'Secondary Haemosiderosis (transfusion-dependent)'),
        ('porphyria',            'Porphyria Cutanea Tarda'),
        ('other',                'Other'),
    ]
    STATUSES = [
        ('scheduled',  'Scheduled'),
        ('completed',  'Completed'),
        ('cancelled',  'Cancelled'),
        ('declined',   'Patient Declined'),
    ]
    DISPOSITIONS = [
        ('discard',      'Discard (not suitable for transfusion)'),
        ('manufacture',  'Manufacture into Allogeneic Component'),
    ]

    patient          = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='therapeutic_phlebotomies')
    indication       = models.CharField(max_length=25, choices=INDICATIONS)
    indication_notes = models.CharField(max_length=500, blank=True)

    scheduled_date   = models.DateField()
    performed_date   = models.DateField(null=True, blank=True)

    target_volume_ml = models.SmallIntegerField(default=450)
    actual_volume_ml = models.SmallIntegerField(null=True, blank=True)

    # Pre-procedure labs
    hb_pre_g_dl      = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    hb_post_g_dl     = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    haematocrit_pre  = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True,
                                           help_text='Haematocrit % (e.g. 52.3)')
    haematocrit_post = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    ferritin_pre_ug_l = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True,
                                            help_text='Ferritin µg/L (target <50 for haemochromatosis)')

    # Vitals pre-procedure
    bp_systolic      = models.SmallIntegerField(null=True, blank=True)
    bp_diastolic     = models.SmallIntegerField(null=True, blank=True)
    pulse_bpm        = models.SmallIntegerField(null=True, blank=True)
    weight_kg        = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)

    status           = models.CharField(max_length=15, choices=STATUSES, default='scheduled')
    disposition      = models.CharField(max_length=15, choices=DISPOSITIONS, default='discard',
                                        help_text='What happens to the collected blood')
    # If manufactured into a component, link to the resulting donation record
    donation         = models.OneToOneField(
        'donors.Donation', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='therapeutic_phlebotomy',
    )

    performed_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                          on_delete=models.PROTECT, related_name='+')
    authorised_by    = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                          on_delete=models.PROTECT, related_name='+')
    notes            = models.TextField(blank=True)
    branch           = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    created_by       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_date']

    def __str__(self):
        return f"TP #{self.pk} — Patient #{self.patient_id} — {self.get_indication_display()} ({self.status})"


# ─── Antenatal Anti-D Programme ───────────────────────────────────────────────

class AntenatalRecord(models.Model):
    """
    Antenatal blood bank record.  Tracks maternal blood group, antibody
    screening schedule, and Anti-D prophylaxis for RhD-negative women.

    RCOG/BCSH Guidelines 2014: all RhD-negative pregnant women should receive
    Routine Antenatal Anti-D Prophylaxis (RAADP) unless sensitised.
    Two-dose schedule: 28 weeks + 34 weeks (or 1500 IU at 28–30 weeks).
    """
    OUTCOMES = [
        ('ongoing',      'Ongoing Pregnancy'),
        ('delivered',    'Delivered'),
        ('miscarriage',  'Miscarriage / TFMR'),
        ('stillbirth',   'Stillbirth'),
        ('ectopic',      'Ectopic Pregnancy'),
    ]

    patient                  = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='antenatal_records')
    edd                      = models.DateField(help_text='Estimated Date of Delivery')
    gestation_at_booking_wks = models.SmallIntegerField(null=True, blank=True)

    # Confirmed maternal group (separate from general patient blood group — must be confirmed
    # independently for obstetric care; same field names for clarity)
    abo                      = models.CharField(max_length=2, choices=ABO_CHOICES, blank=True)
    rh_d                     = models.CharField(max_length=10, choices=RH_CHOICES, blank=True)
    rh_d_confirmed_at        = models.DateField(null=True, blank=True)

    is_rh_d_negative         = models.BooleanField(default=False,
                                                    help_text='Derived from rh_d, stored for quick filtering')
    partner_rh_d             = models.CharField(
        max_length=10, blank=True,
        choices=[('pos','Positive'),('neg','Negative'),('unknown','Unknown')],
        help_text='If partner is confirmed Rh-neg, RAADP may not be required',
    )

    outcome                  = models.CharField(max_length=15, choices=OUTCOMES, default='ongoing')
    delivery_date            = models.DateField(null=True, blank=True)
    cord_blood_group_abo     = models.CharField(max_length=2, blank=True,
                                                 help_text='Cord blood ABO (post-delivery)')
    cord_blood_group_rh      = models.CharField(max_length=10, blank=True,
                                                 help_text='Cord blood Rh D (post-delivery; triggers postnatal Anti-D if positive)')

    branch                   = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    created_by               = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at               = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-edd']

    def __str__(self):
        return f"ANC #{self.pk} — Patient #{self.patient_id} — EDD {self.edd}"

    def requires_raadp(self) -> bool:
        """Returns True if patient needs Routine Antenatal Anti-D Prophylaxis."""
        if not self.is_rh_d_negative:
            return False
        if self.partner_rh_d == 'neg':
            return False
        return True

    def raadp_schedule(self) -> list:
        """
        Returns [(label, weeks, due_date), ...] for the two-dose RAADP schedule
        per BCSH/RCOG 2014 (28-week + 34-week doses).
        """
        if not self.requires_raadp():
            return []
        from datetime import timedelta
        w28 = self.edd - timedelta(days=84)   # EDD - 12 weeks = 28 weeks
        w34 = self.edd - timedelta(days=42)   # EDD - 6 weeks  = 34 weeks
        return [
            ('raadp_28w', 28, w28),
            ('raadp_34w', 34, w34),
        ]

    def postnatal_anti_d_required(self) -> bool:
        """True if cord blood is RhD-positive and mother is RhD-negative."""
        return self.is_rh_d_negative and self.cord_blood_group_rh in ('pos', 'weak_d')

    def save(self, *args, **kwargs):
        self.is_rh_d_negative = (self.rh_d == 'neg')
        super().save(*args, **kwargs)


class AntiDProphylaxis(models.Model):
    """
    Record of Anti-D immunoglobulin administration.

    Indications:
    - RAADP: 28 weeks + 34 weeks (Routine Antenatal)
    - Postnatal: within 72 hours of delivery if cord blood is RhD-positive
    - Post-sensitising event (PSE): amniocentesis, APH, ECV, miscarriage, trauma

    Kleihauer-Betke test required for postnatal dose to detect large fetal-maternal
    haemorrhage (FMH) and calculate whether a top-up dose is needed.
    """
    INDICATIONS = [
        ('raadp_28w',       'Routine Antenatal — 28 weeks (RAADP)'),
        ('raadp_34w',       'Routine Antenatal — 34 weeks (RAADP)'),
        ('postnatal',       'Postnatal — within 72 h of delivery'),
        ('pse_amnio',       'PSE — Amniocentesis / Chorionic Villus Sampling'),
        ('pse_aph',         'PSE — Antepartum Haemorrhage'),
        ('pse_ecv',         'PSE — External Cephalic Version'),
        ('pse_miscarriage', 'PSE — Miscarriage / TFMR (> 12 weeks)'),
        ('pse_trauma',      'PSE — Abdominal Trauma'),
        ('pse_other',       'PSE — Other'),
    ]
    PRODUCTS = [
        ('anti_d_500iu',    'Anti-D 500 IU (Rh(D) Immunoglobulin)'),
        ('anti_d_1500iu',   'Anti-D 1500 IU'),
        ('anti_d_2500iu',   'Anti-D 2500 IU'),
        ('anti_d_custom',   'Anti-D Custom Dose (calculated from Kleihauer)'),
    ]

    antenatal_record         = models.ForeignKey(AntenatalRecord, on_delete=models.PROTECT,
                                                  related_name='anti_d_doses')
    indication               = models.CharField(max_length=20, choices=INDICATIONS)
    product                  = models.CharField(max_length=20, choices=PRODUCTS)
    dose_iu                  = models.SmallIntegerField(help_text='Dose in International Units')
    batch_number             = models.CharField(max_length=100)
    expiry_date              = models.DateField()
    administered_at          = models.DateTimeField()
    administered_by          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                                  related_name='+')

    # Kleihauer-Betke (postnatal): detects large fetal-maternal haemorrhage
    kleihauer_done           = models.BooleanField(default=False)
    kleihauer_result_pct     = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True,
                                                    help_text='% fetal cells (Kleihauer-Betke)')
    fmh_volume_ml            = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True,
                                                    help_text='Calculated FMH volume mL')
    additional_dose_required = models.BooleanField(default=False,
                                                    help_text='FMH >4 mL requires extra Anti-D (1500 IU per 4 mL FMH)')

    notes                    = models.TextField(blank=True)
    esign                    = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True,
                                                  on_delete=models.PROTECT, related_name='+')
    created_at               = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-administered_at']

    def __str__(self):
        return (f"Anti-D #{self.pk} — {self.get_indication_display()} — "
                f"Patient #{self.antenatal_record.patient_id} ({self.dose_iu} IU)")


class HaemolyticDiseaseCase(models.Model):
    """
    Haemolytic Disease of the Fetus and Newborn (HDFN) case record.

    Tracks maternal alloimmunisation, serological monitoring, and neonatal
    treatment (phototherapy, exchange transfusion, intrauterine transfusion).

    References: BCSH Guideline for the use of anti-D immunoglobulin 2014;
    NICE CG133 Jaundice in newborn babies; BSH HDFN guidelines 2016.
    """
    SEVERITY = [
        ('mild',     'Mild — phototherapy only'),
        ('moderate', 'Moderate — intensive phototherapy'),
        ('severe',   'Severe — exchange transfusion required'),
        ('iut',      'Severe — intrauterine transfusion required'),
    ]
    OUTCOMES = [
        ('resolved',        'Resolved — no sequelae'),
        ('resolved_hearing','Resolved — hearing loss / bilirubin toxicity'),
        ('ongoing',         'Ongoing — under follow-up'),
        ('transferred',     'Transferred to tertiary centre'),
        ('neonatal_death',  'Neonatal death'),
    ]
    DAT_RESULTS = [
        ('positive',    'Positive'),
        ('negative',    'Negative'),
        ('weakly_pos',  'Weakly Positive'),
        ('not_done',    'Not Done'),
    ]

    mother         = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name='hdfn_cases_mother',
        help_text='Maternal patient record',
    )
    neonate        = models.ForeignKey(
        Patient, null=True, blank=True, on_delete=models.PROTECT,
        related_name='hdfn_cases_neonate',
        help_text='Neonatal patient record (if registered)',
    )
    maternal_antibody = models.ForeignKey(
        PatientAntibody, null=True, blank=True, on_delete=models.PROTECT,
        related_name='+',
        help_text='Causative maternal antibody (leave blank if antibody not yet identified)',
    )
    antibody_specificity_text = models.CharField(
        max_length=100, blank=True,
        help_text='Free text if maternal_antibody FK not set (e.g. "Anti-c, anti-E")',
    )

    # Fetal/Neonatal presentation
    gestational_age_wks      = models.SmallIntegerField(null=True, blank=True,
                                                          help_text='Gestation at delivery (weeks)')
    birth_weight_g           = models.SmallIntegerField(null=True, blank=True, help_text='Birth weight in grams')
    cord_hb_g_dl             = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True,
                                                     help_text='Cord blood Hb at birth (g/dL)')
    direct_antiglobulin_test = models.CharField(max_length=10, choices=DAT_RESULTS, default='not_done')
    peak_bilirubin_umol_l    = models.SmallIntegerField(null=True, blank=True,
                                                         help_text='Peak total bilirubin (µmol/L)')
    hours_at_peak_bilirubin  = models.SmallIntegerField(null=True, blank=True,
                                                         help_text='Age at peak bilirubin (hours of life)')

    # Treatment
    severity                 = models.CharField(max_length=10, choices=SEVERITY, blank=True)
    phototherapy_started     = models.BooleanField(default=False)
    phototherapy_start_date  = models.DateField(null=True, blank=True)
    phototherapy_duration_h  = models.SmallIntegerField(null=True, blank=True,
                                                         help_text='Total phototherapy hours')
    exchange_transfusion_done = models.BooleanField(default=False)
    exchange_transfusion_date = models.DateField(null=True, blank=True)
    num_exchange_volumes      = models.SmallIntegerField(null=True, blank=True,
                                                          help_text='Number of exchange transfusion volumes given')
    iut_required             = models.BooleanField(default=False,
                                                    help_text='Intrauterine transfusion required in utero')
    num_iut_procedures        = models.SmallIntegerField(default=0,
                                                          help_text='Number of IUT procedures performed')
    ivig_given               = models.BooleanField(default=False,
                                                    help_text='Intravenous immunoglobulin given (adjunct to PT)')

    outcome                  = models.CharField(max_length=20, choices=OUTCOMES, blank=True)
    clinical_notes           = models.TextField(blank=True)
    reported_to_haemovigilance = models.BooleanField(default=False,
                                                       help_text='Reported to SHOT/national haemovigilance if exchange needed')

    recorded_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'HDFN Case'
        verbose_name_plural = 'HDFN Cases'

    def antibody_display(self):
        if self.maternal_antibody:
            return self.maternal_antibody.specificity
        return self.antibody_specificity_text or 'Unknown'

    def is_severe(self):
        return self.severity in ('severe', 'iut') or self.exchange_transfusion_done or self.iut_required

    def __str__(self):
        return (f"HDFN #{self.pk} — Mother: Patient #{self.mother_id} — "
                f"{self.antibody_display()} — {self.get_outcome_display() or 'outcome pending'}")
