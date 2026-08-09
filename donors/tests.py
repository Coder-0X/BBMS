from django.test import TestCase
from django.utils import timezone
from donors.models import Donor, Donation


class DonorModelTestCase(TestCase):
    def setUp(self):
        self.donor = Donor.objects.create(
            donor_code='DNR-001',
            full_name='John Doe',
            blood_group='O',
            rh_factor='+',
            phone='9800000000',
            email='john@example.com',
        )

    def test_donor_str_representation(self):
        self.assertIn('DNR-001', str(self.donor))
        self.assertIn('John Doe', str(self.donor))
        self.assertIn('O+', str(self.donor))

    def test_donor_creation(self):
        self.assertEqual(Donor.objects.count(), 1)
        self.assertEqual(self.donor.blood_group, 'O')
        self.assertEqual(self.donor.rh_factor, '+')

    def test_donor_phone_unique(self):
        from donors.forms import DonorForm
        form = DonorForm(data={
            'donor_code': 'DNR-999',
            'full_name': 'Duplicate Phone Donor',
            'blood_group': 'B',
            'rh_factor': '+',
            'phone': '9800000000',
            'gender': 'Male',
            'age': 25,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)


class DonationModelTestCase(TestCase):
    def setUp(self):
        self.donor = Donor.objects.create(
            donor_code='DNR-002',
            full_name='Jane Smith',
            blood_group='A',
            rh_factor='-',
            phone='9811111111',
        )
        self.donation = Donation.objects.create(
            donation_code='DON-001',
            donor=self.donor,
            donation_datetime=timezone.now(),
            quantity_ml=450,
            status='Collected',
        )

    def test_donation_str_representation(self):
        self.assertIn('DON-001', str(self.donation))
        self.assertIn('Jane Smith', str(self.donation))
        self.assertIn('450 mL', str(self.donation))

    def test_donation_status_default(self):
        self.assertEqual(self.donation.status, 'Collected')
        self.assertFalse(self.donation.units_generated)
