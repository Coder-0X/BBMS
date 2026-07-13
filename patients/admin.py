from django.contrib import admin

from .models import BloodIssue, BloodRequest, Crossmatch, Patient

admin.site.register(Patient)
admin.site.register(BloodRequest)
admin.site.register(Crossmatch)
admin.site.register(BloodIssue)
