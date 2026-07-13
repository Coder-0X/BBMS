from django import forms

from core.forms import BootstrapFormMixin

from .models import AuditLog, StaffProfile


class StaffProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = '__all__'


class AuditLogForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = AuditLog
        fields = '__all__'
