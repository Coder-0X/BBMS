from django import forms

from core.forms import BootstrapFormMixin

from .models import AuditLog, StaffProfile


class StaffProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = '__all__'

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not phone or not str(phone).strip():
            return None
        return str(phone).strip()


class AuditLogForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = AuditLog
        fields = '__all__'
