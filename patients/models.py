from datetime import timedelta

from django.db import models
from django.utils import timezone

from core.choices import (
    ABO_CHOICES,
    COMPATIBILITY_RESULT_CHOICES,
    CROSSMATCH_RESERVATION_HOURS,
    CROSSMATCH_STATUS_CHOICES,
    GENDER_CHOICES,
    ISSUE_STATUS_CHOICES,
    REQUEST_STATUS_CHOICES,
    RH_CHOICES,
)
from inventory.models import BloodComponent, BloodUnit


class Patient(models.Model):
    patient_code = models.CharField(max_length=30, unique=True)
    full_name = models.CharField(max_length=150)
    gender = models.CharField(
        max_length=10, choices=GENDER_CHOICES, blank=True, null=True,
    )
    age = models.PositiveIntegerField(blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    diagnosis = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ['full_name']
        indexes = [
            models.Index(fields=['full_name']),
            models.Index(fields=['phone']),
        ]

    def save(self, *args, **kwargs):
        if not self.patient_code or not str(self.patient_code).strip():
            count = Patient.objects.count() + 1
            code = f'PAT-{count:04d}'
            while Patient.objects.filter(patient_code=code).exclude(pk=self.pk).exists():
                count += 1
                code = f'PAT-{count:04d}'
            self.patient_code = code
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        age_str = f', {self.age} yrs' if self.age else ''
        gender_str = f', {self.gender}' if self.gender else ''
        return f'{self.patient_code} - {self.full_name} ({gender_str.lstrip(", ")}{age_str})'.replace(' ()', '')


class BloodRequest(models.Model):
    request_code = models.CharField(max_length=30, unique=True, blank=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    required_blood_group = models.CharField(max_length=5, choices=ABO_CHOICES)
    required_rh = models.CharField(max_length=10, choices=RH_CHOICES)
    required_component = models.ForeignKey(
        BloodComponent,
        on_delete=models.PROTECT,
        help_text='Which component the patient needs (RBC, Plasma, etc.).',
    )
    units_required = models.PositiveIntegerField(default=1)
    request_status = models.CharField(
        max_length=20,
        choices=REQUEST_STATUS_CHOICES,
        default='Pending',
    )
    request_date = models.DateTimeField()

    class Meta:
        ordering = ['-request_date']
        indexes = [
            models.Index(fields=['request_status', 'request_date']),
            models.Index(fields=['required_blood_group', 'required_rh', 'request_status']),
        ]

    def save(self, *args, **kwargs):
        if not self.request_code or not str(self.request_code).strip():
            count = BloodRequest.objects.count() + 1
            code = f'REQ-{count:05d}'
            while BloodRequest.objects.filter(request_code=code).exclude(pk=self.pk).exists():
                count += 1
                code = f'REQ-{count:05d}'
            self.request_code = code
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        pname = self.patient.full_name if self.patient else 'Unknown'
        comp = self.required_component.component_name if self.required_component else 'Blood'
        return f'{self.request_code} - {pname} ({self.required_blood_group}{self.required_rh} {comp}, {self.units_required} unit - {self.request_status})'


class Crossmatch(models.Model):
    crossmatch_code = models.CharField(max_length=30, unique=True, blank=True)
    blood_request = models.ForeignKey(BloodRequest, on_delete=models.CASCADE)
    blood_unit = models.ForeignKey(
        BloodUnit,
        on_delete=models.PROTECT,
        related_name='crossmatches',
        help_text='The inventory unit booked/reserved for this request.',
    )
    crossmatch_status = models.CharField(
        max_length=20,
        choices=CROSSMATCH_STATUS_CHOICES,
        default='Booked',
        editable=False,
    )
    compatibility_result = models.CharField(
        max_length=20,
        choices=COMPATIBILITY_RESULT_CHOICES,
        default='Pending',
        editable=False,
    )
    booked_at = models.DateTimeField(auto_now_add=True)
    reserved_until = models.DateTimeField(
        blank=True,
        null=True,
        editable=False,
        help_text=f'Auto-set to {CROSSMATCH_RESERVATION_HOURS}h after '
        'booking. The reservation is released automatically if the unit '
        'is not issued before this time.',
    )
    crossmatched_at = models.DateTimeField(
        blank=True,
        null=True,
        editable=False,
        help_text='Set automatically when the compatibility test is recorded.',
    )

    class Meta:
        ordering = ['-booked_at']
        indexes = [
            models.Index(fields=['crossmatch_status', 'reserved_until']),
        ]

    def __str__(self) -> str:
        req_code = self.blood_request.request_code if self.blood_request else '?'
        unit_code = self.blood_unit.unit_code if self.blood_unit else '?'
        return f'{self.crossmatch_code} - Req: {req_code} / Unit: {unit_code} ({self.crossmatch_status})'

    def save(self, *args, **kwargs):
        if not self.crossmatch_code or not str(self.crossmatch_code).strip():
            count = Crossmatch.objects.count() + 1
            code = f'CM-{count:05d}'
            while Crossmatch.objects.filter(crossmatch_code=code).exclude(pk=self.pk).exists():
                count += 1
                code = f'CM-{count:05d}'
            self.crossmatch_code = code
        if self.booked_at is None:
            self.booked_at = timezone.now()
        if self.reserved_until is None:
            self.reserved_until = self.booked_at + timedelta(
                hours=CROSSMATCH_RESERVATION_HOURS
            )
        super().save(*args, **kwargs)


class BloodIssue(models.Model):
    issue_code = models.CharField(max_length=30, unique=True, blank=True)
    crossmatch = models.ForeignKey(Crossmatch, on_delete=models.CASCADE)
    issued_to_patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    doctor_name = models.CharField(max_length=150, blank=True, null=True)
    hospital_name = models.CharField(max_length=150, blank=True, null=True)
    issued_datetime = models.DateTimeField()
    issue_status = models.CharField(
        max_length=20, choices=ISSUE_STATUS_CHOICES, default='Issued',
    )

    class Meta:
        ordering = ['-issued_datetime']
        indexes = [
            models.Index(fields=['issue_status', 'issued_datetime']),
        ]

    def save(self, *args, **kwargs):
        if not self.issue_code or not str(self.issue_code).strip():
            count = BloodIssue.objects.count() + 1
            code = f'ISS-{count:05d}'
            while BloodIssue.objects.filter(issue_code=code).exclude(pk=self.pk).exists():
                count += 1
                code = f'ISS-{count:05d}'
            self.issue_code = code
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        pname = self.issued_to_patient.full_name if self.issued_to_patient else 'Unknown'
        return f'{self.issue_code} - {pname} ({self.issue_status})'
