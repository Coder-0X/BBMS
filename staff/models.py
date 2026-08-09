from django.conf import settings
from django.db import models

from core.choices import STAFF_ROLE_CHOICES


class StaffProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    employee_code = models.CharField(max_length=30, unique=True)
    role = models.CharField(
        max_length=20,
        choices=STAFF_ROLE_CHOICES,
        help_text='Determines which sections of the system this user can access.',
    )
    phone = models.CharField(max_length=30, blank=True, null=True)

    class Meta:
        ordering = ['employee_code']

    def __str__(self) -> str:
        return f'{self.employee_code} - {self.get_role_display()}'


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    action_type = models.CharField(max_length=100)
    module_name = models.CharField(max_length=100)
    record_id = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['module_name', 'action_type']),
        ]

    def __str__(self) -> str:
        username = self.user.username if self.user else 'System'
        return f'{self.created_at:%Y-%m-%d %H:%M} | {username} | {self.module_name}: {self.action_type}'
