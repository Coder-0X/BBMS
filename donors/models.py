from django.db import models
from django.conf import settings
from django.utils import timezone


class Donor(models.Model):
    DEFERRAL_STATUS = [
        ('active', 'Active'),
        ('temporary_defer', 'Temporarily Deferred'),
        ('permanent_defer', 'Permanently Deferred'),
    ]
    ABO = [('A','A'),('B','B'),('AB','AB'),('O','O')]
    RH  = [('pos','Positive'),('neg','Negative'),('weak_d','Weak D'),('unknown','Unknown')]

    # PII lives in privacy.SubjectIdentity — this just holds the surrogate key
    subject = models.OneToOneField(
        'privacy.SubjectIdentity',
        on_delete=models.PROTECT,
        related_name='donor',
    )
    sex = models.CharField(max_length=10, choices=[('M','Male'),('F','Female'),('U','Unknown')])
    dob = models.DateField(null=True, blank=True)
    blood_group_abo = models.CharField(max_length=2, choices=ABO, blank=True)
    blood_group_rh  = models.CharField(max_length=10, choices=RH, blank=True)

    deferral_status  = models.CharField(max_length=20, choices=DEFERRAL_STATUS, default='active')
    deferral_reason  = models.CharField(max_length=500, blank=True)
    deferral_until   = models.DateField(null=True, blank=True)
    deferral_set_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )

    total_donations     = models.IntegerField(default=0)
    first_donation_date = models.DateField(null=True, blank=True)
    last_donation_date  = models.DateField(null=True, blank=True)

    registration_branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='donors')
    created_at  = models.DateTimeField(auto_now_add=True)
    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')

    @property
    def category(self) -> str:
        """Retention category based on total donations."""
        n = self.total_donations
        if n == 0: return 'new'
        if n <= 2:  return 'new'
        if n <= 9:  return 'regular'
        if n <= 24: return 'committed'
        return 'veteran'

    @property
    def next_milestone(self):
        """Returns (milestone_type, donations_remaining) for next milestone."""
        n = self.total_donations
        milestones = [(1, 'first'), (5, 'fifth'), (10, 'tenth'), (25, '25th'), (50, '50th'), (100, '100th')]
        for threshold, mtype in milestones:
            if n < threshold:
                return mtype, threshold - n
        return None, 0

    def check_and_create_milestones(self):
        """Create DonorMilestone records for any uncreated milestones."""
        from django.utils import timezone
        n = self.total_donations
        milestones = [(1, 'first'), (5, 'fifth'), (10, 'tenth'), (25, '25th'), (50, '50th'), (100, '100th')]
        today = timezone.now().date()
        for threshold, mtype in milestones:
            if n >= threshold:
                DonorMilestone.objects.get_or_create(
                    donor=self,
                    milestone_type=mtype,
                    defaults={'achieved_at': today},
                )

    MINIMUM_INTERVALS_DAYS = {
        'whole_blood': 56,      # 8 weeks (AABB / WHO Standard: 56 days)
        'apheresis_rbc': 112,   # 16 weeks (2 units RBC)
        'apheresis_plt': 14,    # 2 weeks
        'apheresis_plasma': 28, # 4 weeks
        'apheresis_multi': 56,
    }

    @property
    def days_since_last_donation(self) -> int | None:
        if not self.last_donation_date:
            return None
        return (timezone.now().date() - self.last_donation_date).days

    @property
    def days_until_eligible(self) -> int:
        """Returns days remaining until donor can donate whole blood again."""
        if not self.last_donation_date:
            return 0
        days_passed = self.days_since_last_donation or 0
        min_days = 84 if self.sex == 'F' else 56
        return max(0, min_days - days_passed)

    def is_eligible_to_donate(self, donation_type: str = 'whole_blood') -> bool:
        """Comprehensive eligibility check covering permanent deferral, temporary deferral, and donation interval."""
        today = timezone.now().date()
        if self.deferral_status == 'permanent_defer':
            return False
        if self.deferral_status == 'temporary_defer' and self.deferral_until:
            if self.deferral_until >= today:
                return False
        if self.last_donation_date:
            min_days = self.MINIMUM_INTERVALS_DAYS.get(donation_type, 56)
            if self.sex == 'F' and donation_type == 'whole_blood':
                min_days = max(min_days, 84)  # WHO gender-specific iron recovery guideline
            if (today - self.last_donation_date).days < min_days:
                return False
        return True

    def __str__(self):
        return f"Donor #{self.pk}"


class Donation(models.Model):
    TYPES = [
        ('whole_blood', 'Whole Blood'),
        ('apheresis_rbc', 'Apheresis RBC'),
        ('apheresis_plt', 'Apheresis Platelets'),
        ('apheresis_plasma', 'Apheresis Plasma'),
        ('apheresis_multi', 'Apheresis Multi-component'),
    ]
    PURPOSES = [
        ('allogeneic',  'Allogeneic (Routine)'),
        ('autologous',  'Pre-deposit Autologous'),
        ('directed',    'Directed (for named recipient)'),
    ]

    donor = models.ForeignKey(Donor, on_delete=models.PROTECT, related_name='donations')
    branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='donations')
    donated_at = models.DateTimeField()
    donation_type = models.CharField(max_length=20, choices=TYPES)
    # Purpose — allogeneic by default; autologous / directed require patient link
    donation_purpose   = models.CharField(max_length=15, choices=PURPOSES, default='allogeneic')
    intended_recipient = models.ForeignKey(
        'patients.Patient', null=True, blank=True, on_delete=models.PROTECT,
        related_name='directed_donations',
        help_text='Named recipient for directed or autologous donations',
    )
    volume_ml = models.SmallIntegerField(null=True, blank=True)
    bag_lot_number = models.CharField(max_length=50, blank=True)
    collection_set_lot = models.CharField(max_length=50, blank=True)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='donations_collected',
    )
    consent = models.ForeignKey(
        'privacy.ConsentRecord', on_delete=models.PROTECT, related_name='donations',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Donation #{self.pk} by {self.donor} on {self.donated_at:%Y-%m-%d}"


class DonorPhenotype(models.Model):
    """
    Extended red cell phenotyping for a donor.

    Standard systems typed:
    - Rh: C, c, E, e (D is recorded in Donor.blood_group_rh)
    - Kell: K (Kell), k (Cellano)
    - Duffy: Fya, Fyb
    - Kidd: Jka, Jkb
    - MNS: M, N, S, s
    - Lewis: Lea, Leb
    - P1PK: P1

    True = antigen present, False = antigen absent, None = not tested.
    antigen_negative_set() returns antigens the donor LACKS — safe for
    patients who have antibodies to those antigens.
    """
    METHODS = [('serology', 'Serology (tube/gel)'), ('molecular', 'Molecular genotyping')]

    donor     = models.OneToOneField(Donor, on_delete=models.PROTECT, related_name='phenotype')
    typed_at  = models.DateTimeField()
    typed_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    method    = models.CharField(max_length=15, choices=METHODS, default='serology')

    # Rh (partial — D from Donor.blood_group_rh)
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
    created_at = models.DateTimeField(auto_now_add=True)

    ANTIGEN_FIELDS = ['C','c','E','e','K','k','Fya','Fyb','Jka','Jkb','M','N','S','s','Lea','Leb','P1']

    def antigen_negative_set(self) -> dict:
        """
        Returns dict of antigens this donor LACKS.
        e.g. {'K': True, 'E': True} — safe for anti-K, anti-E patients.
        """
        result = {}
        for antigen in self.ANTIGEN_FIELDS:
            val = getattr(self, antigen)
            if val is False:  # explicitly negative (not null = untested)
                result[antigen] = True
        return result

    def antigen_profile(self) -> dict:
        """Full profile including untested fields."""
        return {a: getattr(self, a) for a in self.ANTIGEN_FIELDS}

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._propagate_to_units()

    def _propagate_to_units(self):
        """Update antigen_negative_set on all blood units from this donor."""
        from inventory.models import BloodUnit
        neg_set = self.antigen_negative_set()
        for unit in BloodUnit.objects.filter(donation__donor=self.donor):
            unit.antigen_negative_set = neg_set
            unit.save(update_fields=['antigen_negative_set'])

    def __str__(self):
        return f"Phenotype of Donor #{self.donor_id} ({self.method})"


class DonorMilestone(models.Model):
    """Recognition milestones for donor retention."""
    TYPES = [
        ('first',   '1st Donation'),
        ('fifth',   '5th Donation'),
        ('tenth',   '10th Donation'),
        ('25th',    '25th Donation'),
        ('50th',    '50th Donation'),
        ('100th',   '100th Donation'),
        ('annual',  'Annual Donor'),
    ]

    donor       = models.ForeignKey(Donor, on_delete=models.PROTECT, related_name='milestones')
    milestone_type  = models.CharField(max_length=10, choices=TYPES)
    achieved_at = models.DateField()
    notified    = models.BooleanField(default=False)
    certificate_generated = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('donor', 'milestone_type')]

    def __str__(self):
        return f"Donor #{self.donor_id}: {self.get_milestone_type_display()} on {self.achieved_at}"


class DonorAdverseEvent(models.Model):
    TYPES = [
        ('vasovagal', 'Vasovagal Reaction'),
        ('syncope', 'Syncope/Fainting'),
        ('hematoma', 'Hematoma'),
        ('nerve_injury', 'Nerve Injury'),
        ('citrate_reaction', 'Citrate Reaction'),
        ('arterial_puncture', 'Arterial Puncture'),
        ('other', 'Other'),
    ]
    SEVERITY = [('mild','Mild'),('moderate','Moderate'),('severe','Severe')]
    OUTCOMES = [
        ('full_recovery', 'Full Recovery'),
        ('ongoing', 'Ongoing'),
        ('medical_referral', 'Medical Referral'),
        ('hospitalized', 'Hospitalized'),
    ]

    donation = models.OneToOneField(Donation, on_delete=models.PROTECT, related_name='adverse_event')
    donor = models.ForeignKey(Donor, on_delete=models.PROTECT, related_name='adverse_events')
    event_type = models.CharField(max_length=30, choices=TYPES)
    severity = models.CharField(max_length=10, choices=SEVERITY)
    loss_of_consciousness = models.BooleanField(default=False)
    injury = models.BooleanField(default=False)
    treatment = models.TextField(blank=True)
    outcome = models.CharField(max_length=20, choices=OUTCOMES)
    reportable = models.BooleanField(default=False)
    report_ref = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_event_type_display()} for {self.donor} ({self.get_severity_display()})"


class RetentionCampaign(models.Model):
    """
    Organized donor re-engagement drive targeting a specific lapsed-donor segment.

    Blood banks lose 15–20% of donors per year. A campaign tracks which lapsed
    donors were contacted, how they responded, and whether they re-donated —
    enabling ROI calculation per outreach effort.
    """
    CHANNEL_CHOICES = [
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('call', 'Phone Call'),
        ('letter', 'Letter'),
        ('mixed', 'Mixed'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('closed', 'Closed'),
    ]
    SEGMENT_CHOICES = [
        ('lapsed_3m', 'Lapsed 3+ months'),
        ('lapsed_6m', 'Lapsed 6+ months'),
        ('lapsed_12m', 'Lapsed 12+ months'),
        ('new_never_returned', 'First-time, never returned'),
        ('specific_group', 'Specific blood group'),
        ('high_value', 'Veteran donors (10+ donations)'),
        ('custom', 'Custom'),
    ]

    name       = models.CharField(max_length=200)
    branch     = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='retention_campaigns')
    segment    = models.CharField(max_length=30, choices=SEGMENT_CHOICES)
    target_abo = models.CharField(max_length=2, blank=True,
                                  choices=[('A','A'),('B','B'),('AB','AB'),('O','O')],
                                  help_text='Leave blank for all ABO groups')
    target_rh  = models.CharField(max_length=10, blank=True,
                                  choices=[('pos','Positive'),('neg','Negative'),('','All')],
                                  help_text='Leave blank for all Rh types')
    channel    = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    message_template = models.TextField(
        help_text='Use {name} and {last_donation} as placeholders.'
    )
    goal_donations = models.PositiveIntegerField(default=0, help_text='Target number of re-donations')
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    start_date = models.DateField(null=True, blank=True)
    end_date   = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    notes      = models.TextField(blank=True)

    def enrolled_count(self):
        return self.enrollments.count()

    def response_count(self):
        return self.enrollments.filter(status__in=['responded', 'appointment_booked', 'donated']).count()

    def donated_count(self):
        return self.enrollments.filter(status='donated').count()

    def response_rate(self):
        total = self.enrolled_count()
        return round(self.response_count() / total * 100, 1) if total else 0

    def conversion_rate(self):
        total = self.enrolled_count()
        return round(self.donated_count() / total * 100, 1) if total else 0

    def __str__(self):
        return f"Campaign '{self.name}' ({self.get_status_display()})"


class CampaignEnrollment(models.Model):
    """Tracks the outreach and response status for one donor in one campaign."""
    STATUS_CHOICES = [
        ('enrolled', 'Enrolled — not yet contacted'),
        ('contacted', 'Contacted'),
        ('responded', 'Responded'),
        ('appointment_booked', 'Appointment Booked'),
        ('donated', 'Re-donated'),
        ('declined', 'Declined'),
        ('unreachable', 'Unreachable'),
        ('ineligible', 'Became Ineligible'),
    ]

    campaign    = models.ForeignKey(RetentionCampaign, on_delete=models.PROTECT, related_name='enrollments')
    donor       = models.ForeignKey(Donor, on_delete=models.PROTECT, related_name='campaign_enrollments')
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='enrolled')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    contacted_at   = models.DateTimeField(null=True, blank=True)
    responded_at   = models.DateTimeField(null=True, blank=True)
    donated_at     = models.DateTimeField(null=True, blank=True)
    outcome_notes  = models.TextField(blank=True)
    updated_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                       on_delete=models.PROTECT, related_name='+')

    class Meta:
        unique_together = [('campaign', 'donor')]

    def __str__(self):
        return f"{self.donor} in {self.campaign} — {self.get_status_display()}"


class DonorHealthQuestionnaire(models.Model):
    """
    Donor Health History Questionnaire (DHQ) completed before each donation.

    Required by: AABB Standards §5.5.1, FDA Guidance 2023 (Revised Recommendations
    for Reducing the Risk of HIV), EU Directive 2004/33/EC Annex II, WHO Blood
    Donor Selection Guidelines Chapter 3.

    The questionnaire must be donor-signed, reviewed by trained staff, and retained
    for a minimum of 10 years (AABB) / indefinitely (FDA for SDAs).
    """
    TRAVEL_RISK = [
        ('none', 'No travel to risk areas'),
        ('malaria_zone', 'Travel to malaria-endemic area'),
        ('cjd_risk', 'Lived in UK 1980–1996 (vCJD risk)'),
        ('other_risk', 'Other risk-area travel'),
    ]

    donor     = models.ForeignKey(Donor, on_delete=models.PROTECT, related_name='health_questionnaires')
    donation  = models.OneToOneField(
        'Donation', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='health_questionnaire',
    )
    completed_at   = models.DateTimeField()
    completed_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+',
    )
    reviewed_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    reviewed_at    = models.DateTimeField(null=True, blank=True)

    # ── Vital signs (recorded by staff at collection) ──
    weight_kg      = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    hb_g_dl        = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    bp_systolic    = models.SmallIntegerField(null=True, blank=True)
    bp_diastolic   = models.SmallIntegerField(null=True, blank=True)
    pulse          = models.SmallIntegerField(null=True, blank=True)
    temperature_c  = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)

    # ── Section 1: General health ──
    feeling_well          = models.BooleanField()
    recent_illness        = models.BooleanField()
    recent_illness_detail = models.TextField(blank=True)
    on_antibiotics        = models.BooleanField()
    on_other_medications  = models.BooleanField()
    medications_detail    = models.TextField(blank=True)

    # ── Section 2: Donation history ──
    donated_elsewhere_recently = models.BooleanField()
    donated_elsewhere_detail   = models.TextField(blank=True)

    # ── Section 3: Infections and travel ──
    recent_infection      = models.BooleanField()
    recent_infection_detail = models.TextField(blank=True)
    travel_risk           = models.CharField(max_length=15, choices=TRAVEL_RISK, default='none')
    travel_detail         = models.TextField(blank=True)
    malaria_history       = models.BooleanField()

    # ── Section 4: Blood-borne virus risk factors ──
    # All questions use WHO / FDA 2023 language
    tattoo_or_piercing_12m = models.BooleanField(
        help_text='Tattoo, piercing, or acupuncture in the past 12 months',
    )
    needlestick_12m        = models.BooleanField(
        help_text='Accidental needlestick or contact with someone else\'s blood in past 12 months',
    )
    sti_history            = models.BooleanField(
        help_text='Diagnosed with an STI (syphilis, gonorrhoea, chlamydia, herpes) in past 12 months',
    )
    new_sexual_partner_3m  = models.BooleanField(
        help_text='New sexual partner(s) in the past 3 months',
    )
    # FDA 2023 MSM/TSM question uses 3-month deferral
    sexual_contact_risk_3m = models.BooleanField(
        help_text='Sexual contact with a person whose HIV status is unknown or positive, in past 3 months',
    )
    sex_for_money_or_drugs = models.BooleanField(
        help_text='Exchanged sex for money or drugs at any time',
    )
    iv_drug_use_ever       = models.BooleanField(
        help_text='Ever injected recreational drugs (including steroids) not prescribed by a doctor',
    )

    # ── Section 5: Medical history ──
    prior_transfusion      = models.BooleanField()
    prior_transfusion_date = models.DateField(null=True, blank=True)
    prior_transplant       = models.BooleanField()
    prior_transplant_detail = models.TextField(blank=True)
    pregnancy_6m           = models.BooleanField(
        help_text='Pregnant or given birth in the past 6 months',
    )
    cancer_history         = models.BooleanField()
    heart_disease_history  = models.BooleanField()
    bleeding_disorder      = models.BooleanField()
    diabetes               = models.BooleanField()
    cjd_risk_factor        = models.BooleanField(
        help_text='Family history of CJD, or received dura mater/corneal transplant or growth hormone before 1985',
    )

    # ── Outcome ──
    OUTCOMES = [
        ('eligible',   'Eligible — donation proceeded'),
        ('deferred_temp', 'Temporarily Deferred'),
        ('deferred_perm', 'Permanently Deferred'),
        ('self_excluded', 'Self-Excluded (donor withdrew)'),
    ]
    outcome            = models.CharField(max_length=15, choices=OUTCOMES, blank=True)
    deferral_reasons   = models.TextField(blank=True)
    donor_signature    = models.BooleanField(default=False,
        help_text='Donor signed/confirmed answers are true and complete',
    )
    staff_signature    = models.BooleanField(default=False,
        help_text='Staff member reviewed and accepted the questionnaire',
    )
    notes              = models.TextField(blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-completed_at']

    def has_deferral_triggers(self) -> list:
        """
        Returns a list of deferral reason strings based on answered questions.
        Used to auto-populate the outcome before staff review.
        Empty list = no automatic triggers found (staff must still review).
        """
        reasons = []
        if self.iv_drug_use_ever:
            reasons.append("IV drug use — permanent deferral (AABB / FDA)")
        if self.sex_for_money_or_drugs:
            reasons.append("Sex for money or drugs — permanent deferral (AABB / FDA)")
        if self.malaria_history:
            reasons.append("History of malaria — minimum 3-year deferral from last symptom (WHO)")
        if self.prior_transfusion:
            reasons.append("Prior transfusion received — 4-month deferral from date of transfusion (WHO §4.2)")
        if self.prior_transplant:
            reasons.append("Prior organ/tissue transplant — may require permanent deferral (FDA)")
        if self.cjd_risk_factor:
            reasons.append("CJD risk factor — permanent deferral (AABB / MHRA)")
        if self.on_antibiotics:
            reasons.append("Currently on antibiotics — defer until 2 weeks after completing course")
        if self.tattoo_or_piercing_12m:
            reasons.append("Tattoo/piercing in past 12 months — 12-month deferral (unless licensed studio)")
        if self.sti_history:
            reasons.append("STI in past 12 months — 3–12 month deferral depending on STI type")
        if self.pregnancy_6m:
            reasons.append("Pregnant/post-partum within 6 months — defer until 6 months post-delivery")
        if self.recent_illness:
            reasons.append("Recent illness reported — review detail before proceeding")
        if self.sexual_contact_risk_3m:
            reasons.append("Sexual contact with HIV-risk partner in past 3 months — 3-month deferral (FDA 2023)")
        if self.needlestick_12m:
            reasons.append("Needlestick/blood exposure in past 12 months — 4-month deferral (WHO)")
        if self.travel_risk in ('malaria_zone', 'cjd_risk', 'other_risk'):
            reasons.append(f"Travel risk: {self.get_travel_risk_display()} — see local deferral policy")
        return reasons

    def __str__(self):
        return f"DHQ for {self.donor} on {self.completed_at:%Y-%m-%d}"
