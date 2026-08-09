from django import forms
from django.utils import timezone

from core.forms import BootstrapFormMixin

from .models import BloodIssue, BloodRequest, Patient


def get_next_patient_code() -> str:
    count = Patient.objects.count() + 1
    code = f'PAT-{count:04d}'
    while Patient.objects.filter(patient_code=code).exists():
        count += 1
        code = f'PAT-{count:04d}'
    return code


def get_next_request_code() -> str:
    count = BloodRequest.objects.count() + 1
    code = f'REQ-{count:05d}'
    while BloodRequest.objects.filter(request_code=code).exists():
        count += 1
        code = f'REQ-{count:05d}'
    return code


def get_next_issue_code() -> str:
    count = BloodIssue.objects.count() + 1
    code = f'ISS-{count:05d}'
    while BloodIssue.objects.filter(issue_code=code).exists():
        count += 1
        code = f'ISS-{count:05d}'
    return code


class PatientForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Patient
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.initial.get('patient_code'):
            self.fields['patient_code'].initial = get_next_patient_code()
        self.fields['patient_code'].required = False
        self.fields['patient_code'].help_text = (
            'Auto-generated. You can also customize it.'
        )
        self.fields['phone'].help_text = 'Contact phone number.'

    def clean_patient_code(self):
        code = self.cleaned_data.get('patient_code')
        if not code or not str(code).strip():
            return get_next_patient_code()
        code = str(code).strip()
        qs = Patient.objects.filter(patient_code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'Patient code "{code}" is already taken.')
        return code

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not phone or not str(phone).strip():
            return None
        phone = str(phone).strip()
        if not phone.isdigit() or len(phone) < 7:
            raise forms.ValidationError('Please enter a valid phone number.')
        return phone


class BloodRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodRequest
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            if not self.initial.get('request_code'):
                self.fields['request_code'].initial = get_next_request_code()
            if not self.initial.get('request_date'):
                self.fields['request_date'].initial = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        self.fields['request_code'].required = False
        self.fields['request_code'].help_text = (
            'Auto-generated. You can also customize it.'
        )

    def clean_request_code(self):
        code = self.cleaned_data.get('request_code')
        if not code or not str(code).strip():
            return get_next_request_code()
        code = str(code).strip()
        qs = BloodRequest.objects.filter(request_code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'Request code "{code}" is already taken.')
        return code


class BloodIssueForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodIssue
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            if not self.initial.get('issue_code'):
                self.fields['issue_code'].initial = get_next_issue_code()
            if not self.initial.get('issued_datetime'):
                self.fields['issued_datetime'].initial = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        self.fields['issue_code'].required = False
        self.fields['issue_code'].help_text = (
            'Auto-generated. You can also customize it.'
        )
        # Only crossmatches that passed and haven't already been issued
        # against are valid to hand out blood for.
        self.fields['crossmatch'].queryset = self.fields[
            'crossmatch'
        ].queryset.filter(crossmatch_status='Passed')

    def clean_issue_code(self):
        code = self.cleaned_data.get('issue_code')
        if not code or not str(code).strip():
            return get_next_issue_code()
        code = str(code).strip()
        qs = BloodIssue.objects.filter(issue_code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'Issue code "{code}" is already taken.')
        return code
