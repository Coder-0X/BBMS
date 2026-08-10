from django import forms
from django.utils import timezone

from core.forms import BootstrapFormMixin

from .models import Donation, Donor


def get_next_donor_code() -> str:
    count = Donor.objects.count() + 1
    code = f'DNR-{count:04d}'
    while Donor.objects.filter(donor_code=code).exists():
        count += 1
        code = f'DNR-{count:04d}'
    return code


def get_next_donation_code() -> str:
    count = Donation.objects.count() + 1
    code = f'DON-{count:05d}'
    while Donation.objects.filter(donation_code=code).exists():
        count += 1
        code = f'DON-{count:05d}'
    return code


class DonorForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Donor
        fields = [
            'donor_code',
            'full_name',
            'dob',
            'nin',
            'blood_group',
            'rh_factor',
            'phone',
            'email',
            'is_deferred',
            'deferral_reason',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.initial.get('donor_code'):
            self.fields['donor_code'].initial = get_next_donor_code()
        self.fields['donor_code'].required = False
        
        if 'dob' in self.fields:
            self.fields['dob'].widget.attrs['class'] = self.fields['dob'].widget.attrs.get('class', '') + ' nepali-datepicker'
            self.fields['dob'].widget.attrs['placeholder'] = 'YYYY-MM-DD'
            self.fields['dob'].widget.attrs['autocomplete'] = 'off'

        self.fields['deferral_reason'].help_text = 'Reason if donor is deferred (e.g. infection, medical condition).'

    def clean_donor_code(self):
        code = self.cleaned_data.get('donor_code')
        if not code or not str(code).strip():
            return get_next_donor_code()
        code = str(code).strip()
        qs = Donor.objects.filter(donor_code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'Donor code "{code}" is already taken.')
        return code

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not phone or not str(phone).strip():
            return None
        phone = str(phone).strip()
        if not phone.isdigit() or len(phone) != 10:
            raise forms.ValidationError('Phone number must be exactly 10 digits.')
        qs = Donor.objects.filter(phone=phone)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            existing = qs.first()
            raise forms.ValidationError(
                f'This phone number is already registered to donor "{existing.full_name}" ({existing.donor_code}).'
            )
        return phone


class DonationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Donation
        fields = [
            'donation_code',
            'donor',
            'donation_datetime',
            'quantity_ml',
            'status',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exclude deferred donors from new donation form
        self.fields['donor'].queryset = Donor.objects.filter(is_deferred=False)
        if not self.instance.pk:
            if not self.initial.get('donation_code'):
                self.fields['donation_code'].initial = get_next_donation_code()
            if not self.initial.get('donation_datetime'):
                self.fields['donation_datetime'].initial = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            if not self.initial.get('quantity_ml'):
                self.fields['quantity_ml'].initial = 450
        self.fields['donation_code'].required = False


    def clean_donor(self):
        donor = self.cleaned_data.get('donor')
        if donor and donor.is_deferred:
            raise forms.ValidationError(
                f'Donor {donor.donor_code} ({donor.full_name}) is permanently deferred ({donor.deferral_reason}) and cannot donate.'
            )
        return donor

    def clean_donation_code(self):
        code = self.cleaned_data.get('donation_code')
        if not code or not str(code).strip():
            return get_next_donation_code()
        code = str(code).strip()
        qs = Donation.objects.filter(donation_code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'Donation code "{code}" is already taken.')
        return code

    def clean_quantity_ml(self):
        qty = self.cleaned_data.get('quantity_ml')
        if qty is not None:
            if qty < 300:
                raise forms.ValidationError('Minimum donation volume is 300 mL.')
            if qty > 500:
                raise forms.ValidationError('Maximum donation volume is 500 mL.')
        return qty
