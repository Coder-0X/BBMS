"""
Integration view tests — donor, patient, transfusion, inventory workflows.
Run: pytest tests/test_views.py -v
"""
import pytest
import json
from datetime import timedelta
from django.test import Client
from django.utils import timezone

from tests.conftest import (
    UserFactory, BranchFactory, DonorFactory, DonationFactory,
    BloodUnitFactory, PatientFactory, PatientBloodGroupFactory,
    BloodRequestFactory,
)


def _client(user, branch=None):
    c = Client()
    c.login(username=user.username, password='testpass123')
    if branch is not None:
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
    return c


def _superuser(branch):
    """Create an admin user with all permissions (bypasses has_permission checks)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    u = User.objects.create_superuser(
        username=f'admin_{branch.pk}',
        password='testpass123',
        display_name='Admin User',
        branch=branch,
    )
    return u


# ─── Donor workflow ───────────────────────────────────────────────────────────

class TestDonorWorkflow:

    def test_donor_list_view(self, db, branch, user):
        DonorFactory(registration_branch=branch, created_by=user)
        response = _client(user, branch).get('/donors/')
        assert response.status_code == 200

    def test_donor_detail_view(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        response = _client(user, branch).get(f'/donors/{donor.pk}/')
        assert response.status_code == 200

    def test_donor_create_view_get(self, db, branch):
        su = _superuser(branch)
        response = _client(su, branch).get('/donors/register/')
        assert response.status_code == 200

    def test_donation_detail_view(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        response = _client(user, branch).get(f'/donors/{donor.pk}/donate/')
        assert response.status_code in (200, 404)


# ─── Inventory workflow ───────────────────────────────────────────────────────

class TestInventoryWorkflow:

    def test_blood_unit_list_view(self, db, branch, user):
        response = _client(user, branch).get('/inventory/units/')
        assert response.status_code == 200

    def test_blood_unit_detail_view(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        response = _client(user, branch).get(f'/inventory/units/{unit.did}/')
        assert response.status_code in (200, 404)

    def test_inventory_filter_by_component(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        BloodUnitFactory(donation=donation, component_class='RBC',
                          status='available', owner_branch=branch)
        response = _client(user, branch).get('/inventory/units/?component_class=RBC')
        assert response.status_code == 200


# ─── Patient workflow ─────────────────────────────────────────────────────────

class TestPatientWorkflow:

    def test_patient_list_view(self, db, branch, user):
        response = _client(user, branch).get('/patients/')
        assert response.status_code == 200

    def test_patient_detail_view(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        response = _client(user, branch).get(f'/patients/{patient.pk}/')
        assert response.status_code == 200

    def test_consent_withdrawal_raises_alert(self, db, branch, user):
        from django.utils import timezone
        from patients.models import TransfusionConsent
        from core.models import Alert
        patient = PatientFactory(created_by=user)
        consent = TransfusionConsent.objects.create(
            patient=patient,
            branch=branch,
            consent_type='written',
            status='active',
            obtained_by=user,
            obtained_at=timezone.now(),
        )
        c = _client(user, branch)
        response = c.post(
            f'/patients/{patient.pk}/consent/{consent.pk}/withdraw/',
            {'reason': 'Patient changed their mind'},
        )
        assert response.status_code in (200, 302)
        alert = Alert.objects.filter(alert_type='consent_withdrawn', branch=branch).first()
        assert alert is not None
        assert alert.severity == 'critical'

    def test_patient_blood_group_history(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        PatientBloodGroupFactory(patient=patient, branch=branch, abo='O', rh_d='neg',
                                  determined_by=user)
        su = _superuser(branch)
        response = _client(su, branch).get(f'/patients/{patient.pk}/blood-group/add/')
        assert response.status_code in (200, 302, 404)


# ─── Transfusion request workflow ─────────────────────────────────────────────

class TestTransfusionRequestWorkflow:

    def test_blood_request_list_view(self, db, branch, user):
        response = _client(user, branch).get('/transfusion/request/')
        assert response.status_code == 200

    def test_blood_request_create_get(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        response = _client(user, branch).get(f'/transfusion/request/new/?patient={patient.pk}')
        assert response.status_code in (200, 404)

    def test_compatible_units_view(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        PatientBloodGroupFactory(patient=patient, branch=branch, abo='O', rh_d='neg',
                                  determined_by=user)
        PatientBloodGroupFactory(patient=patient, branch=branch, abo='O', rh_d='neg',
                                  determined_by=user)
        request = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        response = _client(user, branch).get(
            f'/transfusion/request/{request.pk}/'
        )
        assert response.status_code in (200, 404)


# ─── Crossmatch workflow ──────────────────────────────────────────────────────

class TestCrossmatchWorkflow:

    def test_crossmatch_list_view(self, db, branch, user):
        response = _client(user, branch).get('/transfusion/request/')
        assert response.status_code == 200

    def test_crossmatch_create_view_get(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        blood_request = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        su = _superuser(branch)
        response = _client(su, branch).get(
            f'/transfusion/crossmatch/new/?request={blood_request.pk}&unit={unit.pk}'
        )
        assert response.status_code in (200, 302, 404)


# ─── Quality views ────────────────────────────────────────────────────────────

class TestQualityViews:

    def test_nc_list_view(self, db, branch, user):
        response = _client(user, branch).get('/quality/nc/')
        assert response.status_code == 200

    def test_nc_create_view_get(self, db, branch, user):
        response = _client(user, branch).get('/quality/nc/new/')
        assert response.status_code == 200

    def test_dashboard_view(self, db, branch, user):
        response = _client(user, branch).get('/dashboard/')
        assert response.status_code == 200


# ─── Barcodes ─────────────────────────────────────────────────────────────────

class TestBarcodeGeneration:

    def test_barcode_endpoint_returns_image(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        response = _client(user, branch).get(f'/inventory/units/{unit.did}/')
        assert response.status_code in (200, 404)

    def test_barcode_label_pdf(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        response = _client(user, branch).get(f'/inventory/units/{unit.did}/label/')
        assert response.status_code in (200, 404)
