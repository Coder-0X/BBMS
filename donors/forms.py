from django import forms

from core.forms import BootstrapFormMixin

from .models import Donation, Donor


class DonorForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Donor
        fields = '__all__'


class DonationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Donation
        fields = '__all__'
