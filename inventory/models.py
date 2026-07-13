from django.db import models


class BloodComponent(models.Model):
    component_name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ['component_name']

    def __str__(self) -> str:
        return self.component_name


class BloodUnit(models.Model):
    unit_code = models.CharField(max_length=40, unique=True)
    component = models.ForeignKey(BloodComponent, on_delete=models.CASCADE)
    blood_group = models.CharField(max_length=5)
    rh_factor = models.CharField(max_length=10)
    quantity_ml = models.PositiveIntegerField()
    expiry_date = models.DateField()
    unit_state = models.CharField(max_length=20, default='Available')

    class Meta:
        ordering = ['-expiry_date']

    def __str__(self) -> str:
        return self.unit_code


class Inventory(models.Model):
    blood_unit = models.OneToOneField(BloodUnit, on_delete=models.CASCADE)
    available_quantity = models.PositiveIntegerField()
    reserved_quantity = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=100, blank=True, null=True)
    storage_status = models.CharField(max_length=20, default='Available')

    def __str__(self) -> str:
        return f'{self.blood_unit} ({self.available_quantity})'
