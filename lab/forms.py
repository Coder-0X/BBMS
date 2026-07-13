from django import forms

from core.forms import BootstrapFormMixin

from .models import BloodTest


class BloodTestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodTest
        fields = '__all__'
