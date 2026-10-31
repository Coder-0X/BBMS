from django.db import models
from django.conf import settings


class ComplianceJurisdiction(models.Model):
    name = models.CharField(max_length=200)
    country_code = models.CharField(max_length=2, unique=True)

    def __str__(self):
        return f"{self.country_code} — {self.name}"


class ComplianceRuleset(models.Model):
    """
    A versioned, dated package of compliance rules for one jurisdiction.
    Once status is 'active', it's locked — no edits allowed.
    Changes mean creating a new version.
    """
    STATUS = [('draft', 'Draft'), ('active', 'Active'), ('superseded', 'Superseded')]

    jurisdiction = models.ForeignKey(ComplianceJurisdiction, on_delete=models.PROTECT, related_name='rulesets')
    version = models.CharField(max_length=20)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default='draft')
    locked = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('jurisdiction', 'version')]

    def save(self, *args, **kwargs):
        if self.pk:
            original = ComplianceRuleset.objects.filter(pk=self.pk).first()
            if original and original.locked:
                # Once locked, only lifecycle transitions are allowed — the
                # actual rule content is frozen. Changing anything else means
                # creating a new version.
                allowed_fields = {'status', 'effective_to', 'locked'}
                changed = [
                    f.name for f in self._meta.concrete_fields
                    if getattr(self, f.attname) != getattr(original, f.attname)
                ]
                disallowed = [f for f in changed if f not in allowed_fields]
                if disallowed:
                    raise ValueError("This ruleset is locked. Create a new version to make changes.")
        if self.status == 'active':
            self.locked = True
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.jurisdiction.country_code} v{self.version} ({self.status})"


class ComplianceRule(models.Model):
    """
    One rule within a ruleset. The engine evaluates these rows at runtime.
    Adding a new country = loading rows. No code changes needed.
    """
    KINDS = [
        ('AGE', 'Minimum Age'),
        ('WEIGHT', 'Minimum Weight'),
        ('HB', 'Hemoglobin'),
        ('BP_SYSTOLIC', 'Systolic BP'),
        ('BP_DIASTOLIC', 'Diastolic BP'),
        ('PULSE', 'Pulse'),
        ('DONATION_INTERVAL', 'Donation Interval (days)'),
        ('DEFERRAL', 'Deferral Condition'),
        ('REQUIRED_TEST', 'Required TTI Test'),
        ('RETENTION', 'Record Retention (years)'),
        ('LABEL_FORMAT', 'Label Format'),
        ('MAX_VOLUME', 'Maximum Collection Volume (ml)'),
    ]
    OPERATORS = [
        ('gt', '>'), ('lt', '<'), ('gte', '>='), ('lte', '<='),
        ('eq', '='), ('between', 'Between'), ('required', 'Required'), ('forbidden', 'Forbidden'),
    ]
    APPLIES_TO = [
        ('donor_eligibility', 'Donor Eligibility'),
        ('unit_release', 'Unit Release'),
        ('record_retention', 'Record Retention'),
        ('labeling', 'Labeling'),
    ]

    ruleset = models.ForeignKey(ComplianceRuleset, on_delete=models.CASCADE, related_name='rules')
    rule_kind = models.CharField(max_length=30, choices=KINDS)
    applies_to = models.CharField(max_length=30, choices=APPLIES_TO)
    operator = models.CharField(max_length=10, choices=OPERATORS)
    threshold_value = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    threshold_value_2 = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    threshold_unit = models.CharField(max_length=50, blank=True)
    # JSON conditions like {"sex": "F"} — extra constraints on when this rule applies
    applies_predicate = models.JSONField(null=True, blank=True)
    citation = models.CharField(max_length=500)

    def __str__(self):
        return f"{self.ruleset} / {self.rule_kind} {self.operator} {self.threshold_value}"


class RetentionPolicy(models.Model):
    """How long each record class must be kept. Default is 30 years (EU traceability)."""
    record_class = models.CharField(max_length=100, primary_key=True)
    min_retention_years = models.SmallIntegerField()
    indefinite = models.BooleanField(default=False)
    legal_authority = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name_plural = 'retention policies'

    def __str__(self):
        if self.indefinite:
            return f"{self.record_class} — indefinite"
        return f"{self.record_class} — {self.min_retention_years} years"
