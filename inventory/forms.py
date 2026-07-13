from django import forms

from core.forms import BootstrapFormMixin

from .models import BloodComponent, BloodUnit, Inventory


class BloodComponentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodComponent
        fields = '__all__'


class BloodUnitForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodUnit
        fields = '__all__'


class InventoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Inventory
        fields = '__all__'
