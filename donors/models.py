from django.db import models


class Donor(models.Model):
    donor_code = models.CharField(max_length=30, unique=True)
    full_name = models.CharField(max_length=150)
    blood_group = models.CharField(max_length=5)
    rh_factor = models.CharField(max_length=10)
    phone = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['full_name']

    def __str__(self) -> str:
        return f'{self.donor_code} - {self.full_name}'


class Donation(models.Model):
    donation_code = models.CharField(max_length=30, unique=True)
    donor = models.ForeignKey(Donor, on_delete=models.CASCADE)
    donation_datetime = models.DateTimeField()
    quantity_ml = models.PositiveIntegerField()
    status = models.CharField(max_length=20, default='Collected')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-donation_datetime']

    def __str__(self) -> str:
        return self.donation_code
