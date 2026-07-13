from django.db import models

from donors.models import Donation


class BloodTest(models.Model):
    donation = models.ForeignKey(Donation, on_delete=models.CASCADE)
    abo_group = models.CharField(max_length=5)
    rh_factor = models.CharField(max_length=10)
    hemoglobin = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
    )
    hiv_result = models.CharField(max_length=20, default='Pending')
    hbv_result = models.CharField(max_length=20, default='Pending')
    hcv_result = models.CharField(max_length=20, default='Pending')
    syphilis_result = models.CharField(max_length=20, default='Pending')
    malaria_result = models.CharField(max_length=20, default='Pending')
    overall_result = models.CharField(max_length=10, default='Pass')
    tested_at = models.DateTimeField()

    class Meta:
        ordering = ['-tested_at']

    def __str__(self) -> str:
        return f'{self.donation} - {self.abo_group}{self.rh_factor}'
