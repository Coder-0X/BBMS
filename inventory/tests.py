from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from inventory.models import BloodComponent, BloodUnit, Inventory


class BloodInventoryTestCase(TestCase):
    def setUp(self):
        self.rbc, _ = BloodComponent.objects.get_or_create(
            component_name='Packed Red Blood Cells',
            defaults={'shelf_life_days': 42, 'ml_per_unit': 450},
        )
        self.plasma, _ = BloodComponent.objects.get_or_create(
            component_name='Fresh Frozen Plasma',
            defaults={'shelf_life_days': 365, 'ml_per_unit': 200},
        )

    def test_expiry_date_auto_calculation(self):
        now = timezone.now()
        unit = BloodUnit.objects.create(
            unit_code='U-RBC-001',
            component=self.rbc,
            blood_group='O',
            rh_factor='+',
            quantity_ml=450,
            collected_at=now,
        )
        expected_expiry = (now + timedelta(days=42)).date()
        self.assertEqual(unit.expiry_date, expected_expiry)
        self.assertFalse(unit.is_expired)

    def test_units_available_property(self):
        unit = BloodUnit.objects.create(
            unit_code='U-FFP-001',
            component=self.plasma,
            blood_group='A',
            rh_factor='+',
            quantity_ml=400,
            collected_at=timezone.now(),
        )
        # 400ml / 200ml per unit = 2.0 units
        self.assertEqual(unit.units_available, 2.0)

    def test_blood_unit_queryset_filters(self):
        now = timezone.now()
        u1 = BloodUnit.objects.create(
            unit_code='U-AVAIL-1',
            component=self.rbc,
            blood_group='O',
            rh_factor='+',
            quantity_ml=450,
            collected_at=now,
            unit_state='Available',
        )
        u2 = BloodUnit.objects.create(
            unit_code='U-RESV-1',
            component=self.rbc,
            blood_group='O',
            rh_factor='+',
            quantity_ml=450,
            collected_at=now,
            unit_state='Reserved',
        )
        self.assertEqual(BloodUnit.objects.filter(unit_state='Available').count(), 1)
        self.assertEqual(BloodUnit.objects.filter(unit_state='Reserved').count(), 1)
        self.assertEqual(BloodUnit.objects.filter(unit_state='Available').first().unit_code, 'U-AVAIL-1')
