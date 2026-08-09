from django.db import models

from core.choices import (
    ABO_CHOICES,
    HEMOGLOBIN_FAIL_CUTOFF,
    OVERALL_RESULT_CHOICES,
    RH_CHOICES,
    TEST_RESULT_CHOICES,
)
from donors.models import Donation


class BloodTest(models.Model):
    donation = models.ForeignKey(Donation, on_delete=models.CASCADE)
    abo_group = models.CharField(max_length=5, choices=ABO_CHOICES)
    rh_factor = models.CharField(max_length=10, choices=RH_CHOICES)
    hemoglobin = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=f'g/dL. Auto-fails below {HEMOGLOBIN_FAIL_CUTOFF} g/dL.',
    )
    hiv_result = models.CharField(
        max_length=20, choices=TEST_RESULT_CHOICES, default='Pending',
    )
    hbv_result = models.CharField(
        max_length=20, choices=TEST_RESULT_CHOICES, default='Pending',
    )
    hcv_result = models.CharField(
        max_length=20, choices=TEST_RESULT_CHOICES, default='Pending',
    )
    syphilis_result = models.CharField(
        max_length=20, choices=TEST_RESULT_CHOICES, default='Pending',
    )
    malaria_result = models.CharField(
        max_length=20, choices=TEST_RESULT_CHOICES, default='Pending',
    )
    overall_result = models.CharField(
        max_length=10,
        choices=OVERALL_RESULT_CHOICES,
        default='Pending',
        editable=False,
        help_text='Calculated automatically from the results above.',
    )
    tested_at = models.DateTimeField()

    class Meta:
        ordering = ['-tested_at']
        indexes = [
            models.Index(fields=['overall_result']),
            models.Index(fields=['tested_at']),
        ]

    def __str__(self) -> str:
        return f'{self.donation} - {self.abo_group}{self.rh_factor}'

    # -- auto verification -------------------------------------------------
    DISEASE_FIELDS = (
        'hiv_result',
        'hbv_result',
        'hcv_result',
        'syphilis_result',
        'malaria_result',
    )

    def failure_reasons(self):
        """Return a list of human-readable reasons this test fails, if any."""
        reasons = []
        if self.hemoglobin is not None and self.hemoglobin < HEMOGLOBIN_FAIL_CUTOFF:
            reasons.append(
                f'Hemoglobin {self.hemoglobin} g/dL is below the '
                f'{HEMOGLOBIN_FAIL_CUTOFF} g/dL cutoff.'
            )
        labels = {
            'hiv_result': 'HIV',
            'hbv_result': 'Hepatitis B',
            'hcv_result': 'Hepatitis C',
            'syphilis_result': 'Syphilis',
            'malaria_result': 'Malaria',
        }
        for field_name in self.DISEASE_FIELDS:
            if getattr(self, field_name) == 'Positive':
                reasons.append(f'{labels[field_name]} screen positive.')
        return reasons

    def compute_overall_result(self):
        """Pending until hemoglobin + every disease marker is filled in;
        Fail if any check fails; Pass otherwise."""
        if self.failure_reasons():
            return 'Fail'
        if self.hemoglobin is None:
            return 'Pending'
        if any(getattr(self, f) == 'Pending' for f in self.DISEASE_FIELDS):
            return 'Pending'
        return 'Pass'

    def save(self, *args, **kwargs):
        self.overall_result = self.compute_overall_result()
        super().save(*args, **kwargs)
