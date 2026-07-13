from django.contrib import admin

from .models import AuditLog, StaffProfile

admin.site.register(StaffProfile)
admin.site.register(AuditLog)
