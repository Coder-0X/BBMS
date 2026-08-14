from django import forms

from core.forms import BootstrapFormMixin
from donors.models import Donation

from .models import BloodComponent, BloodUnit, Inventory


class BloodComponentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodComponent
        fields = '__all__'


class BloodUnitForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BloodUnit
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unit_code'].required = False
        self.fields['unit_code'].help_text = (
            'Optional. Leave blank to auto-generate unit code.'
        )
        self.fields['blood_group'].required = False
        self.fields['blood_group'].help_text = (
            'Auto-filled from donation donor if left blank.'
        )
        self.fields['rh_factor'].required = False
        self.fields['rh_factor'].help_text = (
            'Auto-filled from donation donor if left blank.'
        )
        # Show all donations that passed lab testing
        self.fields['donation'].queryset = Donation.objects.filter(
            status='Passed'
        ).select_related('donor')
        self.fields['donation'].help_text = (
            'Select any donation that has PASSED lab screening. '
            'Leave blank for external/legacy units.'
        )

    def clean_unit_code(self):
        code = self.cleaned_data.get('unit_code')
        if not code or not str(code).strip():
            return ''
        code = str(code).strip()
        qs = BloodUnit.objects.filter(unit_code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'Blood unit code "{code}" is already taken.')
        return code

    def clean(self):
        cleaned_data = super().clean()
        donation = cleaned_data.get('donation')
        quantity_ml = cleaned_data.get('quantity_ml')

        if donation:
            # 1. Guard against rejected or unverified donations
            if donation.status == 'Rejected':
                self.add_error(
                    'donation',
                    'This donation failed lab screening (e.g. low hemoglobin or infection) '
                    'and was REJECTED. It cannot enter inventory or be converted into units.',
                )
            elif donation.status in ('Collected', 'Testing'):
                self.add_error(
                    'donation',
                    'This donation has not passed lab screening yet. Lab staff must '
                    'verify and pass it before it can be separated into components.',
                )

            # Auto-fill blood group and rh factor from donation donor if not provided
            if not cleaned_data.get('blood_group') and donation.donor:
                cleaned_data['blood_group'] = donation.donor.blood_group
                self.instance.blood_group = donation.donor.blood_group
            if not cleaned_data.get('rh_factor') and donation.donor:
                cleaned_data['rh_factor'] = donation.donor.rh_factor
                self.instance.rh_factor = donation.donor.rh_factor

            # 2. Guard against volume allocations exceeding donation capacity
            if quantity_ml is not None:
                if quantity_ml > donation.quantity_ml:
                    self.add_error(
                        'quantity_ml',
                        f'Quantity ({quantity_ml} mL) cannot exceed the total collected '
                        f'donation volume of {donation.quantity_ml} mL.',
                    )
                else:
                    # Check cumulative volume against donation volume
                    existing_qs = donation.blood_units.all()
                    if self.instance and self.instance.pk:
                        existing_qs = existing_qs.exclude(pk=self.instance.pk)
                    other_vol = sum(u.quantity_ml for u in existing_qs)
                    if other_vol + quantity_ml > round(donation.quantity_ml * 1.1):
                        self.add_error(
                            'quantity_ml',
                            f'Total units volume for this donation ({other_vol + quantity_ml} mL) '
                            f'exceeds collected volume ({donation.quantity_ml} mL).',
                        )
        else:
            if not cleaned_data.get('blood_group'):
                self.add_error('blood_group', 'Blood group is required when no donation is linked.')
            if not cleaned_data.get('rh_factor'):
                self.add_error('rh_factor', 'Rh factor is required when no donation is linked.')
            if not cleaned_data.get('collected_at'):
                self.add_error('collected_at', 'Collection date is required when no donation is linked.')

        return cleaned_data


class InventoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Inventory
        fields = '__all__'
