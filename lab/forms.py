from django import forms

from core.forms import BootstrapFormMixin
from donors.models import Donation

from .models import BloodTest


class BloodTestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodTest
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show donations that are awaiting lab screening
        valid_donations = Donation.objects.filter(
            status__in=['Collected', 'Testing'],
        )
        if self.instance and self.instance.pk and self.instance.donation_id:
            valid_donations = valid_donations | Donation.objects.filter(pk=self.instance.donation_id)
        self.fields['donation'].queryset = valid_donations.select_related('donor').distinct()
        self.fields['donation'].help_text = (
            'Select a collected donation awaiting laboratory screening.'
        )
        if 'abo_group' in self.fields:
            self.fields['abo_group'].help_text = (
                'Confirmed ABO group from lab testing. Authoritative and updates the donor record.'
            )
        if 'rh_factor' in self.fields:
            self.fields['rh_factor'].help_text = (
                'Confirmed Rh factor from lab testing. Authoritative and updates the donor record.'
            )
