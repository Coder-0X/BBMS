from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from inventory.models import BloodComponent, BloodUnit, Inventory
from patients import services
from patients.models import Patient, BloodRequest, Crossmatch, BloodIssue


class PatientWorkflowTestCase(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create(
            patient_code='PAT-001',
            full_name='Alice Wonderland',
            gender='Female',
            age=28,
            phone='9841000000',
            diagnosis='Severe Anemia',
        )
        self.component, _ = BloodComponent.objects.get_or_create(
            component_name='Packed Red Blood Cells',
            defaults={'shelf_life_days': 42, 'ml_per_unit': 450},
        )
        self.unit = BloodUnit.objects.create(
            unit_code='U-PAT-TEST-1',
            component=self.component,
            blood_group='O',
            rh_factor='+',
            quantity_ml=450,
            collected_at=timezone.now(),
            unit_state='Available',
        )
        self.inventory = self.unit.inventory
        self.blood_request = BloodRequest.objects.create(
            request_code='REQ-001',
            patient=self.patient,
            required_blood_group='O',
            required_rh='+',
            required_component=self.component,
            units_required=1,
            request_status='Pending',
            request_date=timezone.now(),
        )

    def test_matching_units_for_request(self):
        matches = services.matching_units_for_request(self.blood_request)
        self.assertEqual(matches.count(), 1)
        self.assertEqual(matches.first().unit_code, self.unit.unit_code)

    def test_patient_creation_and_str(self):
        self.assertEqual(Patient.objects.count(), 1)
        self.assertIn('PAT-001', str(self.patient))
        self.assertIn('Alice Wonderland', str(self.patient))

    def test_crossmatch_booking_and_compatibility_flow(self):
        # 1. Book unit
        cm = services.book_unit(self.blood_request, self.unit, 'CM-TEST-100')
        self.assertEqual(cm.crossmatch_status, 'Booked')
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.unit_state, 'Reserved')
        self.blood_request.refresh_from_db()
        self.assertEqual(self.blood_request.request_status, 'Booked')
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.reserved_quantity, 450)
        self.assertEqual(self.inventory.available_quantity, 0)

        # 2. Record Compatible
        cm_pass = services.record_compatibility_result(cm, is_compatible=True)
        self.assertEqual(cm_pass.compatibility_result, 'Compatible')
        self.assertEqual(cm_pass.crossmatch_status, 'Passed')

        # 3. Issue Unit
        services.issue_unit(cm_pass)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.unit_state, 'Issued')
        self.blood_request.refresh_from_db()
        self.assertEqual(self.blood_request.request_status, 'Fulfilled')

    def test_incompatible_crossmatch_releases_unit(self):
        cm = services.book_unit(self.blood_request, self.unit, 'CM-TEST-200')
        services.record_compatibility_result(cm, is_compatible=False)

        self.unit.refresh_from_db()
        self.assertEqual(self.unit.unit_state, 'Available')
        self.blood_request.refresh_from_db()
        self.assertEqual(self.blood_request.request_status, 'Pending')
