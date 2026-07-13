from django.conf import settings
from django.db import models


class StaffProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    employee_code = models.CharField(max_length=30, unique=True)
    role_name = models.CharField(max_length=50)
    phone = models.CharField(max_length=30, blank=True, null=True)

    class Meta:
        ordering = ['employee_code']

    def __str__(self) -> str:
        return f'{self.employee_code} - {self.role_name}'


class AuditLog(models.Model):
    action_type = models.CharField(max_length=100)
    module_name = models.CharField(max_length=100)
    record_id = models.PositiveIntegerField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.module_name}: {self.action_type}'
