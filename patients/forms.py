from django import forms

from core.forms import BootstrapFormMixin

from .models import BloodIssue, BloodRequest, Crossmatch, Patient


class PatientForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Patient
        fields = '__all__'


class BloodRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodRequest
        fields = '__all__'


class CrossmatchForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Crossmatch
        fields = '__all__'


class BloodIssueForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodIssue
        fields = '__all__'
