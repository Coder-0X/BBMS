from django.db import models

from core.choices import (
    ABO_CHOICES,
    DONATION_STATUS_CHOICES,
    RH_CHOICES,
)


class Donor(models.Model):
    donor_code = models.CharField(max_length=30, unique=True, blank=True)
    full_name = models.CharField(max_length=150)
    blood_group = models.CharField(max_length=5, choices=ABO_CHOICES)
    rh_factor = models.CharField(max_length=10, choices=RH_CHOICES)
    phone = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    is_deferred = models.BooleanField(
        default=False,
        help_text='Flagged if donor has medical deferral or post-donation infection recall (e.g. HIV/Hepatitis).',
    )
    deferral_reason = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['full_name']
        indexes = [
            models.Index(fields=['blood_group', 'rh_factor']),
            models.Index(fields=['is_deferred']),
        ]

    def save(self, *args, **kwargs):
        if not self.donor_code or not str(self.donor_code).strip():
            count = Donor.objects.count() + 1
            code = f'DNR-{count:04d}'
            while Donor.objects.filter(donor_code=code).exclude(pk=self.pk).exists():
                count += 1
                code = f'DNR-{count:04d}'
            self.donor_code = code
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        phone_part = f', {self.phone}' if self.phone else ''
        deferred_part = f' [DEFERRED: {self.deferral_reason}]' if self.is_deferred else ''
        return f'{self.donor_code} - {self.full_name} ({self.blood_group}{self.rh_factor}{phone_part}){deferred_part}'


class Donation(models.Model):
    donation_code = models.CharField(max_length=30, unique=True, blank=True)
    donor = models.ForeignKey(Donor, on_delete=models.CASCADE)
    donation_datetime = models.DateTimeField(
        help_text='Exact date/time the blood was drawn from the donor. '
        'This is the reference point used to calculate expiry for every '
        'component split from this donation.',
    )
    quantity_ml = models.PositiveIntegerField(
        help_text='Total whole-blood volume collected, in mL.',
    )
    status = models.CharField(
        max_length=20,
        choices=DONATION_STATUS_CHOICES,
        default='Collected',
    )
    # Set automatically once lab screening passes and component blood
    # units have been generated from this donation, so it never happens
    # twice even if the test record is edited again later.
    units_generated = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-donation_datetime']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['donation_datetime']),
        ]

    def save(self, *args, **kwargs):
        if not self.donation_code or not str(self.donation_code).strip():
            count = Donation.objects.count() + 1
            code = f'DON-{count:05d}'
            while Donation.objects.filter(donation_code=code).exclude(pk=self.pk).exists():
                count += 1
                code = f'DON-{count:05d}'
            self.donation_code = code
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        group = f'{self.donor.blood_group}{self.donor.rh_factor}' if self.donor else '?'
        return f'{self.donation_code} - {self.donor.full_name} ({group}, {self.quantity_ml} mL - {self.status})'
