from django.db import models


class Patient(models.Model):
    patient_code = models.CharField(max_length=30, unique=True)
    full_name = models.CharField(max_length=150)
    gender = models.CharField(max_length=10, blank=True, null=True)
    age = models.PositiveIntegerField(blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    diagnosis = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ['full_name']

    def __str__(self) -> str:
        return f'{self.patient_code} - {self.full_name}'


class BloodRequest(models.Model):
    request_code = models.CharField(max_length=30, unique=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    required_blood_group = models.CharField(max_length=5)
    required_rh = models.CharField(max_length=10)
    required_component = models.CharField(max_length=60)
    units_required = models.PositiveIntegerField(default=1)
    request_status = models.CharField(max_length=20, default='Pending')
    request_date = models.DateTimeField()

    class Meta:
        ordering = ['-request_date']

    def __str__(self) -> str:
        return self.request_code


class Crossmatch(models.Model):
    crossmatch_code = models.CharField(max_length=30, unique=True)
    blood_request = models.ForeignKey(BloodRequest, on_delete=models.CASCADE)
    compatibility_result = models.CharField(
        max_length=20,
        default='Compatible',
    )
    reserved_until = models.DateTimeField(blank=True, null=True)
    crossmatched_at = models.DateTimeField()

    class Meta:
        ordering = ['-crossmatched_at']

    def __str__(self) -> str:
        return self.crossmatch_code


class BloodIssue(models.Model):
    issue_code = models.CharField(max_length=30, unique=True)
    crossmatch = models.ForeignKey(Crossmatch, on_delete=models.CASCADE)
    issued_to_patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    doctor_name = models.CharField(max_length=150, blank=True, null=True)
    hospital_name = models.CharField(max_length=150, blank=True, null=True)
    issued_datetime = models.DateTimeField()
    issue_status = models.CharField(max_length=20, default='Issued')

    class Meta:
        ordering = ['-issued_datetime']

    def __str__(self) -> str:
        return self.issue_code
