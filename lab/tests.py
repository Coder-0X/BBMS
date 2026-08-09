from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from donors.models import Donor, Donation
from lab.models import BloodTest


class BloodTestModelTestCase(TestCase):
    def setUp(self):
        self.donor = Donor.objects.create(
            donor_code='DNR-TEST',
            full_name='Test Donor',
            blood_group='B',
            rh_factor='+',
        )
        self.donation = Donation.objects.create(
            donation_code='DON-TEST',
            donor=self.donor,
            donation_datetime=timezone.now(),
            quantity_ml=450,
        )

    def test_blood_test_pass(self):
        test = BloodTest.objects.create(
            donation=self.donation,
            abo_group='B',
            rh_factor='+',
            hemoglobin=Decimal('14.2'),
            hiv_result='Negative',
            hbv_result='Negative',
            hcv_result='Negative',
            syphilis_result='Negative',
            malaria_result='Negative',
            tested_at=timezone.now(),
        )
        self.assertEqual(test.overall_result, 'Pass')
        self.assertEqual(len(test.failure_reasons()), 0)

    def test_blood_test_fail_low_hemoglobin(self):
        test = BloodTest.objects.create(
            donation=self.donation,
            abo_group='B',
            rh_factor='+',
            hemoglobin=Decimal('10.5'),  # Below 12.5 cutoff
            hiv_result='Negative',
            hbv_result='Negative',
            hcv_result='Negative',
            syphilis_result='Negative',
            malaria_result='Negative',
            tested_at=timezone.now(),
        )
        self.assertEqual(test.overall_result, 'Fail')
        reasons = test.failure_reasons()
        self.assertEqual(len(reasons), 1)
        self.assertIn('below the 12.5 g/dL cutoff', reasons[0])

    def test_blood_test_fail_disease_positive(self):
        test = BloodTest.objects.create(
            donation=self.donation,
            abo_group='B',
            rh_factor='+',
            hemoglobin=Decimal('13.5'),
            hiv_result='Positive',
            hbv_result='Negative',
            hcv_result='Negative',
            syphilis_result='Negative',
            malaria_result='Negative',
            tested_at=timezone.now(),
        )
        self.assertEqual(test.overall_result, 'Fail')
        reasons = test.failure_reasons()
        self.assertIn('HIV screen positive.', reasons)

    def test_blood_test_pending(self):
        test = BloodTest.objects.create(
            donation=self.donation,
            abo_group='B',
            rh_factor='+',
            hemoglobin=Decimal('13.5'),
            hiv_result='Pending',
            tested_at=timezone.now(),
        )
        self.assertEqual(test.overall_result, 'Pending')
