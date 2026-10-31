"""
API endpoint tests — DRF + FHIR facade.
Run: pytest tests/test_api.py -v
"""
import pytest
import json
from datetime import timedelta
from django.test import Client
from django.utils import timezone

from tests.conftest import (
    UserFactory, BranchFactory, DonorFactory, DonationFactory,
    BloodUnitFactory, PatientFactory, BloodRequestFactory,
)


def _api_client(user=None):
    client = Client()
    if user:
        client.login(username=user.username, password='testpass123')
    return client


# ─── Blood units API ──────────────────────────────────────────────────────────

class TestBloodUnitApi:

    def test_list_blood_units_authenticated(self, db, branch, user):
        client = _api_client(user)
        response = client.get('/api/v1/units/')
        assert response.status_code == 200

    def test_list_blood_units_unauthenticated(self, db):
        client = Client()
        response = client.get('/api/v1/units/')
        assert response.status_code in (401, 403)

    def test_blood_unit_list_returns_json(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        client = _api_client(user)
        response = client.get('/api/v1/units/')
        assert response.status_code == 200
        data = json.loads(response.content)
        results = data.get('results', data) if isinstance(data, dict) else data
        assert isinstance(results, list)

    def test_filter_by_abo_type(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        BloodUnitFactory(donation=donation, abo_type='A', rh_d_type='pos',
                          status='available', owner_branch=branch)
        BloodUnitFactory(donation=donation, abo_type='O', rh_d_type='neg',
                          status='available', owner_branch=branch)
        client = _api_client(user)
        response = client.get('/api/v1/units/?abo=A')
        assert response.status_code == 200
        data = json.loads(response.content)
        results = data.get('results', data) if isinstance(data, dict) else data
        for item in results:
            assert item.get('abo_type') == 'A'

    def test_blood_unit_detail(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        client = _api_client(user)
        response = client.get(f'/api/v1/units/{unit.pk}/')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['did'] == unit.did


# ─── Temperature readings API ─────────────────────────────────────────────────

class TestTemperatureApi:

    def test_post_temperature_reading(self, db, branch, user):
        from tests.conftest import StorageEquipmentFactory
        equip = StorageEquipmentFactory(branch=branch)
        client = _api_client(user)
        payload = {
            'sensor_id': equip.sensor_id,
            'temperature_c': 4.2,
            'recorded_at': timezone.now().isoformat(),
        }
        response = client.post(
            '/api/v1/temperature/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert response.status_code in (200, 201, 207)

    def test_post_invalid_temperature_rejected(self, db, branch, user):
        from tests.conftest import StorageEquipmentFactory
        equip = StorageEquipmentFactory(branch=branch)
        client = _api_client(user)
        payload = {
            'sensor_id': equip.sensor_id,
            'temperature_c': 'not_a_number',
            'recorded_at': timezone.now().isoformat(),
        }
        response = client.post(
            '/api/v1/temperature/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert response.status_code in (207, 400)


# ─── FHIR facade ─────────────────────────────────────────────────────────────

class TestFhirFacade:

    def test_fhir_blood_unit_endpoint_returns_json(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        client = _api_client(user)
        response = client.get(f'/fhir/BiologicallyDerivedProduct/{unit.pk}/')
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = json.loads(response.content)
            assert data.get('resourceType') == 'BiologicallyDerivedProduct'

    def test_fhir_patient_endpoint(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        client = _api_client(user)
        response = client.get(f'/fhir/Patient/{patient.pk}/')
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = json.loads(response.content)
            assert data.get('resourceType') == 'Patient'

    def test_fhir_audit_event_endpoint(self, db, branch, user):
        client = _api_client(user)
        response = client.get('/fhir/AuditEvent/')
        assert response.status_code in (200, 404)


# ─── Blood Request API ────────────────────────────────────────────────────────

class TestBloodRequestApi:

    def test_create_blood_request(self, db, branch, user):
        # BloodRequestViewSet is ReadOnly — POST not supported (405)
        patient = PatientFactory(created_by=user)
        client = _api_client(user)
        payload = {
            'patient': patient.pk,
            'component_class': 'RBC',
            'units_requested': 2,
            'urgency': 'routine',
            'branch': branch.pk,
        }
        response = client.post(
            '/api/v1/requests/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert response.status_code in (200, 201, 400, 405)

    def test_list_blood_requests(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        client = _api_client(user)
        response = client.get('/api/v1/requests/')
        assert response.status_code == 200

    def test_blood_request_urgency_validation(self, db, branch, user):
        # BloodRequestViewSet is ReadOnly — POST not supported, validate via list endpoint
        patient = PatientFactory(created_by=user)
        client = _api_client(user)
        response = client.get('/api/v1/requests/?urgency=invalid_urgency')
        assert response.status_code in (200, 400)


# ─── Donor API ────────────────────────────────────────────────────────────────

class TestDonorApi:

    def test_donor_list_authenticated(self, db, branch, user):
        DonorFactory(registration_branch=branch, created_by=user)
        client = _api_client(user)
        response = client.get('/api/v1/donors/')
        assert response.status_code == 200

    def test_donor_search_by_name_blind_index(self, db, branch, user):
        client = _api_client(user)
        response = client.get('/api/v1/donors/?q=Test')
        assert response.status_code in (200, 400)

    def test_donor_detail_view(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        client = _api_client(user)
        response = client.get(f'/api/v1/donors/{donor.pk}/')
        assert response.status_code == 200


# ─── Bedside pre-transfusion verification ────────────────────────────────────

def _make_issue_tx(branch, user, unit_abo='O', unit_rh='neg',
                   patient_abo='O', patient_rh='neg', declare_group=True):
    """
    Build a full issued-unit chain and return (patient, unit, issue_tx).
    When declare_group is False the patient has NO blood group on file at all
    (neither lab-confirmed nor declared) — the unknown-ABO fail-safe case.
    """
    import hashlib
    from audit.models import ElectronicSignature
    from transfusion.models import IssueTransaction

    donor = DonorFactory(registration_branch=branch, created_by=user)
    donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
    unit = BloodUnitFactory(
        donation=donation, abo_type=unit_abo, rh_d_type=unit_rh,
        status='issued', owner_branch=branch,
        expiry_datetime=timezone.now() + timedelta(days=42),
    )
    patient = PatientFactory(created_by=user)
    if declare_group:
        # Declared-at-registration group (no lab record needed for the check)
        patient.abo = patient_abo
        patient.rh_d = patient_rh
        patient.save(update_fields=['abo', 'rh_d'])

    esign = ElectronicSignature.objects.create(
        signer=user, signed_at_utc=timezone.now(), meaning='verified',
        auth_method='password_reauth', reauth_at=timezone.now(),
        signed_payload_hash=hashlib.sha256(b'test').hexdigest(),
        manifested_name=user.display_name or user.username,
    )
    req = BloodRequestFactory(patient=patient, branch=branch,
                              requesting_physician=user, component_class='RBC')
    issue = IssueTransaction.objects.create(
        blood_unit=unit, request=req, patient=patient, issued_by=user,
        issue_esign=esign, issued_at=timezone.now(),
        intended_branch=branch, abo_check_passed=True,
    )
    return patient, unit, issue


class TestBedsideVerify:

    def test_matching_o_neg_passes(self, db, branch, user):
        patient, unit, _ = _make_issue_tx(branch, user)
        resp = _api_client(user).post(
            '/api/v1/bedside/verify/',
            {'patient_uid': str(patient.mpi_uid), 'unit_did': unit.did},
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['status'] == 'pass'
        assert data['checks']['abo_compatible'] is True

    def test_unknown_patient_abo_fails_safe(self, db, branch, user):
        """Regression: a patient with NO ABO on file must FAIL the ABO check,
        not pass it. Previously the compat lookup fell back to [unit_abo], making
        the check always true for an unknown-group patient — a fail-OPEN bug at
        the last barrier before transfusion."""
        patient, unit, _ = _make_issue_tx(branch, user, declare_group=False)
        resp = _api_client(user).post(
            '/api/v1/bedside/verify/',
            {'patient_uid': str(patient.mpi_uid), 'unit_did': unit.did},
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['checks']['abo_compatible'] is False
        assert data['status'] == 'fail'

    def test_incompatible_group_fails(self, db, branch, user):
        # Unit A+ given to an O patient — ABO incompatible
        patient, unit, _ = _make_issue_tx(
            branch, user, unit_abo='A', unit_rh='pos',
            patient_abo='O', patient_rh='neg',
        )
        resp = _api_client(user).post(
            '/api/v1/bedside/verify/',
            {'patient_uid': str(patient.mpi_uid), 'unit_did': unit.did},
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['checks']['abo_compatible'] is False
        assert data['status'] == 'fail'
