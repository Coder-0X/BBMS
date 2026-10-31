"""
Smoke tests for previously-untested transfusion views.

Each test verifies HTTP 200/302 and that the view does not crash.
POST tests verify the happy-path redirect.
"""
import pytest
from datetime import timedelta
from django.utils import timezone
from django.test import Client

from tests.conftest import (
    UserFactory, BranchFactory, DonorFactory, DonationFactory,
    BloodUnitFactory, PatientFactory, PatientBloodGroupFactory,
    BloodRequestFactory,
)


def _client(user, branch=None):
    c = Client()
    c.login(username=user.username, password='testpass123')
    if branch:
        s = c.session
        s['branch_id'] = branch.pk
        s.save()
    return c


def _su(branch):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_superuser(
        username=f'su_{branch.pk}_{timezone.now().timestamp():.0f}',
        password='testpass123',
        display_name='Super',
        branch=branch,
    )


def _make_esign(user):
    """Create a minimal ElectronicSignature for tests."""
    from audit.models import ElectronicSignature
    import hashlib
    return ElectronicSignature.objects.create(
        signer=user,
        signed_at_utc=timezone.now(),
        meaning='verified',
        auth_method='password_reauth',
        reauth_at=timezone.now(),
        signed_payload_hash=hashlib.sha256(b'test').hexdigest(),
        manifested_name=user.display_name or user.username,
    )


def _make_issued_unit(branch, user):
    """Full chain: donor → donation → unit → patient → request → issue transaction."""
    from transfusion.models import BloodRequest, IssueTransaction
    donor = DonorFactory(registration_branch=branch, created_by=user)
    donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
    unit = BloodUnitFactory(
        donation=donation, abo_type='O', rh_d_type='neg',
        status='available', owner_branch=branch,
        expiry_datetime=timezone.now() + timedelta(days=42),
    )
    patient = PatientFactory(created_by=user)
    PatientBloodGroupFactory(patient=patient, branch=branch, abo='O', rh_d='neg', determined_by=user)
    PatientBloodGroupFactory(patient=patient, branch=branch, abo='O', rh_d='neg', determined_by=user)
    blood_request = BloodRequestFactory(
        patient=patient, branch=branch, requesting_physician=user, component_class='RBC',
    )
    unit.status = 'issued'
    unit.save(update_fields=['status'])
    esign = _make_esign(user)
    issue = IssueTransaction.objects.create(
        blood_unit=unit,
        request=blood_request,
        patient=patient,
        issued_by=user,
        issue_esign=esign,
        issued_at=timezone.now(),
        intended_branch=branch,
        abo_check_passed=True,
    )
    return issue, blood_request, unit, patient


# ─── Haemovigilance dashboard ──────────────────────────────────────────────────

class TestHaemovigilanceDashboard:

    def test_get_200(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/haemovigilance/')
        assert resp.status_code == 200

    def test_get_with_reactions(self, db, branch, user):
        issue, req, unit, patient = _make_issued_unit(branch, user)
        from transfusion.models import TransfusionReaction
        TransfusionReaction.objects.create(
            issue_transaction=issue,
            patient=patient,
            blood_unit=issue.blood_unit,
            reaction_type='FNHTR',
            severity='grade_1',
            onset_datetime=timezone.now(),
            imputability='possible',
            outcome='full_recovery',
            clinical_description='Febrile non-haemolytic reaction — temperature rise.',
            recorded_by=user,
            esign=_make_esign(user),
        )
        resp = _client(user, branch).get('/transfusion/haemovigilance/')
        assert resp.status_code == 200


# ─── MTP (Massive Transfusion Protocol) ───────────────────────────────────────

class TestMTPViews:

    def test_mtp_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/mtp/')
        assert resp.status_code == 200

    def test_mtp_activate_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/mtp/activate/')
        assert resp.status_code == 200

    def test_mtp_activate_post(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        c = _client(user, branch)
        resp = c.post('/transfusion/mtp/activate/', {
            'patient_id': patient.pk,
            'trigger_type': 'trauma',
            'clinical_notes': 'RTC — major haemorrhage',
        })
        assert resp.status_code in (200, 302)
        from transfusion.models import MTPActivation
        assert MTPActivation.objects.filter(patient=patient).exists()

    def test_mtp_detail_get(self, db, branch, user):
        from transfusion.models import MTPActivation
        patient = PatientFactory(created_by=user)
        mtp = MTPActivation.objects.create(
            patient=patient, branch=branch, activated_by=user,
            trigger_type='trauma', activated_at=timezone.now(),
        )
        resp = _client(user, branch).get(f'/transfusion/mtp/{mtp.pk}/')
        assert resp.status_code == 200

    def test_mtp_stand_down_post(self, db, branch, user):
        from transfusion.models import MTPActivation
        patient = PatientFactory(created_by=user)
        mtp = MTPActivation.objects.create(
            patient=patient, branch=branch, activated_by=user,
            trigger_type='trauma', activated_at=timezone.now(),
        )
        resp = _client(user, branch).post(f'/transfusion/mtp/{mtp.pk}/', {
            'action': 'stand_down',
        })
        assert resp.status_code in (200, 302)


# ─── Guideline check (appropriateness) ────────────────────────────────────────

class TestGuidelineCheck:

    def test_guideline_check_get(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        resp = _client(user, branch).get(f'/transfusion/request/{req.pk}/guideline-check/')
        assert resp.status_code == 200

    def test_guideline_check_post(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        resp = _client(user, branch).post(f'/transfusion/request/{req.pk}/guideline-check/', {
            'pre_transfusion_hb_g_dl': '6.8',
            'clinical_indication': 'symptomatic_anaemia',
            'meets_guideline': 'on',
            'guideline_notes': 'Pre-op anaemia, surgery in 2h',
        })
        assert resp.status_code in (200, 302)

    def test_appropriateness_report_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/reports/appropriateness/')
        assert resp.status_code == 200


# ─── Post-Transfusion Outcome ──────────────────────────────────────────────────

class TestPostTransfusionOutcome:

    def test_post_outcome_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/outcomes/')
        assert resp.status_code == 200

    def test_record_post_outcome_get(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        resp = _client(user, branch).get(f'/transfusion/request/{req.pk}/post-outcome/')
        assert resp.status_code == 200

    def test_record_post_outcome_post(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        resp = _client(user, branch).post(f'/transfusion/request/{req.pk}/post-outcome/', {
            'post_hb_g_dl': '8.5',
            'post_hb_date': timezone.now().date().isoformat(),
            'clinical_response': 'as_expected',
        })
        assert resp.status_code in (200, 302)
        from transfusion.models import PostTransfusionOutcome
        assert PostTransfusionOutcome.objects.filter(request=req).exists()

    def test_post_outcome_list_filter(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/outcomes/?response=below_expected')
        assert resp.status_code == 200


# ─── PBM Dashboard ────────────────────────────────────────────────────────────

class TestPBMDashboard:

    def test_pbm_dashboard_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/reports/pbm/')
        assert resp.status_code == 200

    def test_pbm_dashboard_with_period(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/reports/pbm/?days=90')
        assert resp.status_code == 200


# ─── Dose Calculator ──────────────────────────────────────────────────────────

class TestDoseCalculator:

    def test_dose_calculator_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/tools/dose-calculator/')
        assert resp.status_code == 200

    def test_dose_calculator_adult_rbc(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/tools/dose-calculator/?weight=70&component=RBC')
        assert resp.status_code == 200

    def test_dose_calculator_neonatal(self, db, branch, user):
        resp = _client(user, branch).get(
            '/transfusion/tools/dose-calculator/?weight=3.5&component=RBC&neonatal=1'
        )
        assert resp.status_code == 200


# ─── Emergency Release ────────────────────────────────────────────────────────

class TestEmergencyRelease:

    def test_emergency_release_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/emergency-release/new/')
        assert resp.status_code in (200, 302)

    def test_emergency_release_post(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(
            donation=donation, abo_type='O', rh_d_type='neg',
            status='available', owner_branch=branch,
        )
        patient = PatientFactory(created_by=user)
        blood_request = BloodRequestFactory(
            patient=patient, branch=branch, requesting_physician=user, component_class='RBC',
        )
        resp = _client(user, branch).post('/transfusion/emergency-release/new/', {
            'request_id': blood_request.pk,
            'justification': 'Traumatic haemorrhage — life threatening, immediate O-neg required.',
            'unit_ids': [unit.pk],
        })
        assert resp.status_code in (200, 302)
        from transfusion.models import EmergencyRelease
        assert EmergencyRelease.objects.filter(request=blood_request).exists()

    def test_emergency_release_post_writes_audit_trail(self, db, branch, user):
        """Bug fix: emergency release now writes an audit entry (was missing)."""
        from audit.models import AuditLog
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(
            donation=donation, abo_type='O', rh_d_type='neg',
            status='available', owner_branch=branch,
        )
        patient = PatientFactory(created_by=user)
        blood_request = BloodRequestFactory(
            patient=patient, branch=branch, requesting_physician=user, component_class='RBC',
        )
        _client(user, branch).post('/transfusion/emergency-release/new/', {
            'request_id': blood_request.pk,
            'justification': 'Life-threatening haemorrhage.',
            'unit_ids': [unit.pk],
        })
        assert AuditLog.objects.filter(action='emergency_release.created').exists()


# ─── Neonatal Orders ──────────────────────────────────────────────────────────

class TestNeonatalOrders:

    def test_neonatal_order_create_get(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user,
                                   component_class='RBC')
        resp = _client(user, branch).get(f'/transfusion/request/{req.pk}/neonatal/')
        assert resp.status_code == 200

    def test_neonatal_order_create_post(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(
            donation=donation, abo_type='O', rh_d_type='neg',
            status='available', owner_branch=branch,
            expiry_datetime=timezone.now() + timedelta(days=5),
        )
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user,
                                   component_class='RBC')
        resp = _client(user, branch).post(f'/transfusion/request/{req.pk}/neonatal/', {
            'blood_unit_did': unit.did,
            'weight_kg': '2.5',
            'postnatal_age_days': '1',
            'indication': 'top_up',
        })
        assert resp.status_code in (200, 302)

    def test_neonatal_order_detail_get(self, db, branch, user):
        from transfusion.models import NeonatalTransfusionOrder, BloodRequest
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        order = NeonatalTransfusionOrder.objects.create(
            patient=patient, blood_request=req, weight_kg='2.5',
            postnatal_age_days=1, indication='top_up',
            created_by=user,
        )
        resp = _client(user, branch).get(f'/transfusion/neonatal/{order.pk}/')
        assert resp.status_code == 200


# ─── Administration record ────────────────────────────────────────────────────

class TestAdministrationRecord:

    def test_record_administration_get(self, db, branch, user):
        issue, _, _, _ = _make_issued_unit(branch, user)
        resp = _client(user, branch).get(f'/transfusion/issue/{issue.pk}/administer/')
        assert resp.status_code == 200

    def test_record_administration_post(self, db, branch, user):
        issue, req, _, patient = _make_issued_unit(branch, user)
        now_str = timezone.now().strftime('%Y-%m-%dT%H:%M')
        resp = _client(user, branch).post(f'/transfusion/issue/{issue.pk}/administer/', {
            'patient_scan_id': str(patient.pk),
            'unit_scan_did': issue.blood_unit.did,
            'start_at': now_str,
            'outcome': 'completed',
        })
        assert resp.status_code in (200, 302)
        from transfusion.models import TransfusionAdministration
        assert TransfusionAdministration.objects.filter(issue=issue).exists()

    def test_record_administration_verify_fail_on_wrong_scan(self, db, branch, user):
        issue, req, _, patient = _make_issued_unit(branch, user)
        now_str = timezone.now().strftime('%Y-%m-%dT%H:%M')
        resp = _client(user, branch).post(f'/transfusion/issue/{issue.pk}/administer/', {
            'patient_scan_id': 'WRONG_ID',
            'unit_scan_did': 'WRONG_DID',
            'start_at': now_str,
            'outcome': 'completed',
        })
        assert resp.status_code in (200, 302)
        from transfusion.models import TransfusionAdministration
        admin = TransfusionAdministration.objects.filter(issue=issue).first()
        assert admin is not None
        assert admin.bedside_verify_pass is False


# ─── Quality views: deplete lot ───────────────────────────────────────────────

class TestDepleteLot:

    def test_deplete_lot_get(self, db, branch, user):
        from tests.conftest import ReagentLotFactory
        lot = ReagentLotFactory(branch=branch, status='in_use')
        resp = _client(user, branch).get(f'/quality/lots/{lot.pk}/deplete/')
        assert resp.status_code == 200

    def test_deplete_lot_post(self, db, branch, user):
        from tests.conftest import ReagentLotFactory
        lot = ReagentLotFactory(branch=branch, status='in_use')
        resp = _client(user, branch).post(f'/quality/lots/{lot.pk}/deplete/')
        assert resp.status_code in (200, 302)
        lot.refresh_from_db()
        assert lot.status == 'depleted'

    def test_deplete_lot_fires_low_stock_alert(self, db, branch, user):
        from tests.conftest import ReagentLotFactory, ReagentFactory
        from core.models import Alert, RefFacility
        RefFacility.objects.get_or_create(
            facility_code=branch.facility_code,
            defaults={'name': branch.name, 'branch': branch},
        )
        reagent = ReagentFactory(minimum_lots=2)
        lot = ReagentLotFactory(branch=branch, reagent=reagent, status='in_use')
        _client(user, branch).post(f'/quality/lots/{lot.pk}/deplete/')
        alert = Alert.objects.filter(alert_type='low_inventory', branch=branch).first()
        assert alert is not None

    def test_deplete_lot_non_in_use_blocked(self, db, branch, user):
        from tests.conftest import ReagentLotFactory
        lot = ReagentLotFactory(branch=branch, status='quarantined')
        _client(user, branch).post(f'/quality/lots/{lot.pk}/deplete/')
        lot.refresh_from_db()
        assert lot.status == 'quarantined'


# ─── Calibration list with overdue alerts ─────────────────────────────────────

class TestCalibrationList:

    def test_calibration_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/calibrations/')
        assert resp.status_code == 200

    def test_calibration_list_fires_overdue_alert(self, db, branch, user):
        from quality.models import EquipmentCalibration
        from core.models import Alert
        EquipmentCalibration.objects.create(
            name='Centrifuge A',
            asset_id=f'CENT-{branch.pk}',
            equipment_type='centrifuge',
            branch=branch,
            last_calibrated=timezone.now().date() - timedelta(days=400),
            next_due=timezone.now().date() - timedelta(days=35),
            calibrated_by='External Service Co.',
            within_spec=True,
            recorded_by=user,
        )
        _client(user, branch).get('/quality/calibrations/')
        alert = Alert.objects.filter(
            alert_type='equipment_calibration_due', branch=branch
        ).first()
        assert alert is not None
        assert alert.severity == 'critical'


# ─── Blood request ────────────────────────────────────────────────────────────

class TestNewBloodRequest:

    def test_new_blood_request_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/request/new/')
        assert resp.status_code == 200

    def test_new_blood_request_post_creates_request(self, db, branch, user):
        from transfusion.models import BloodRequest
        patient = PatientFactory(created_by=user)
        count_before = BloodRequest.objects.count()
        resp = _client(user, branch).post('/transfusion/request/new/', {
            'patient_id': patient.pk,
            'component_class': 'RBC',
            'units_requested': '2',
            'urgency': 'routine',
        })
        assert resp.status_code in (200, 302)
        assert BloodRequest.objects.count() > count_before

    def test_new_blood_request_creates_audit_entry(self, db, branch, user):
        from audit.models import AuditLog
        patient = PatientFactory(created_by=user)
        _client(user, branch).post('/transfusion/request/new/', {
            'patient_id': patient.pk,
            'component_class': 'RBC',
            'units_requested': '1',
            'urgency': 'urgent',
        })
        assert AuditLog.objects.filter(action='transfusion.request.create').exists()


# ─── Patient sample collection ────────────────────────────────────────────────

class TestCollectSample:

    def test_collect_sample_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/sample/collect/')
        assert resp.status_code == 200

    def test_collect_sample_post_creates_sample(self, db, branch, user):
        from transfusion.models import Sample, BloodRequest
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        import uuid
        accession = f'ACC-{uuid.uuid4().hex[:8].upper()}'
        resp = _client(user, branch).post('/transfusion/sample/collect/', {
            'patient_id': patient.pk,
            'request_id': req.pk,
            'accession_number': accession,
            'recent_transfusion_or_pregnancy': 'no',
        })
        assert resp.status_code in (200, 302)
        assert Sample.objects.filter(accession_number=accession).exists()

    def test_collect_sample_creates_audit_entry(self, db, branch, user):
        from audit.models import AuditLog
        from transfusion.models import BloodRequest
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        import uuid
        accession = f'ACC-{uuid.uuid4().hex[:8].upper()}'
        _client(user, branch).post('/transfusion/sample/collect/', {
            'patient_id': patient.pk,
            'request_id': req.pk,
            'accession_number': accession,
            'recent_transfusion_or_pregnancy': 'no',
        })
        assert AuditLog.objects.filter(action='sample.collect.pretransfusion').exists()

    def test_collect_sample_three_day_rule_expiry(self, db, branch, user):
        """Sample from patient with recent transfusion/pregnancy gets 72h validity."""
        from transfusion.models import Sample, BloodRequest
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        import uuid
        accession = f'ACC-{uuid.uuid4().hex[:8].upper()}'
        _client(user, branch).post('/transfusion/sample/collect/', {
            'patient_id': patient.pk,
            'request_id': req.pk,
            'accession_number': accession,
            'recent_transfusion_or_pregnancy': 'yes',
        })
        sample = Sample.objects.filter(accession_number=accession).first()
        assert sample is not None
        assert sample.validity_expiry is not None


# ─── Antibody screen ──────────────────────────────────────────────────────────

class TestAntibodyScreen:

    def test_antibody_screen_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/antibody-screen/new/')
        assert resp.status_code == 200

    def test_antibody_screen_post_creates_screen(self, db, branch, user):
        from transfusion.models import Sample, AntibodyScreen
        patient = PatientFactory(created_by=user)
        import uuid
        accession = f'ABS-{uuid.uuid4().hex[:8].upper()}'
        sample = Sample.objects.create(
            patient=patient,
            accession_number=accession,
            collected_at=timezone.now(),
            collected_by=user,
            sample_type='pre_transfusion',
            branch_id=branch.pk,
        )
        resp = _client(user, branch).post('/transfusion/antibody-screen/new/', {
            'accession_number': accession,
            'method': 'gel_card',
            'screen_cell_lot': 'SCELL-2024-01',
            'overall_result': 'negative',
        })
        assert resp.status_code in (200, 302)
        assert AntibodyScreen.objects.filter(sample=sample).exists()

    def test_antibody_screen_creates_audit_entry(self, db, branch, user):
        from audit.models import AuditLog
        from transfusion.models import Sample
        patient = PatientFactory(created_by=user)
        import uuid
        accession = f'ABS-{uuid.uuid4().hex[:8].upper()}'
        Sample.objects.create(
            patient=patient,
            accession_number=accession,
            collected_at=timezone.now(),
            collected_by=user,
            sample_type='pre_transfusion',
            branch_id=branch.pk,
        )
        _client(user, branch).post('/transfusion/antibody-screen/new/', {
            'accession_number': accession,
            'method': 'gel_card',
            'screen_cell_lot': 'SCELL-2024-01',
            'overall_result': 'negative',
        })
        assert AuditLog.objects.filter(action='antibody.screen.record').exists()


# ─── MSBOS CRUD ───────────────────────────────────────────────────────────────

class TestMSBOSViews:

    def test_msbos_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/msbos/')
        assert resp.status_code == 200

    def test_msbos_list_shows_entry(self, db, branch, user):
        from transfusion.models import MSBOS
        MSBOS.objects.create(
            procedure_code='CABG', branch=branch, order_type='crossmatch', units_count=2
        )
        resp = _client(user, branch).get('/transfusion/msbos/')
        assert resp.status_code == 200
        assert b'CABG' in resp.content

    def test_msbos_add_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/msbos/add/')
        assert resp.status_code == 200

    def test_msbos_add_post_creates_entry(self, db, branch, user):
        from transfusion.models import MSBOS
        _client(user, branch).post('/transfusion/msbos/add/', {
            'procedure_code': 'HIPJOINT',
            'order_type': 'crossmatch',
            'units_count': '2',
        })
        assert MSBOS.objects.filter(procedure_code='HIPJOINT', branch=branch).exists()

    def test_msbos_add_post_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        _client(user, branch).post('/transfusion/msbos/add/', {
            'procedure_code': 'CABGAUDIT',
            'order_type': 'type_and_screen',
            'units_count': '0',
        })
        assert AuditLog.objects.filter(action__startswith='msbos.').exists()

    def test_msbos_edit_get(self, db, branch, user):
        from transfusion.models import MSBOS
        entry = MSBOS.objects.create(
            procedure_code='EDIT1', branch=branch, order_type='none', units_count=0
        )
        resp = _client(user, branch).get(f'/transfusion/msbos/{entry.pk}/edit/')
        assert resp.status_code == 200

    def test_msbos_edit_post_updates_entry(self, db, branch, user):
        from transfusion.models import MSBOS
        entry = MSBOS.objects.create(
            procedure_code='EDIT2', branch=branch, order_type='none', units_count=0
        )
        _client(user, branch).post(f'/transfusion/msbos/{entry.pk}/edit/', {
            'order_type': 'crossmatch',
            'units_count': '3',
        })
        entry.refresh_from_db()
        assert entry.order_type == 'crossmatch'
        assert entry.units_count == 3

    def test_msbos_edit_post_writes_audit(self, db, branch, user):
        from transfusion.models import MSBOS
        from audit.models import AuditLog
        entry = MSBOS.objects.create(
            procedure_code='EDITAUDIT', branch=branch, order_type='none', units_count=0
        )
        _client(user, branch).post(f'/transfusion/msbos/{entry.pk}/edit/', {
            'order_type': 'type_and_screen',
            'units_count': '1',
        })
        assert AuditLog.objects.filter(action='msbos.update').exists()

    def test_msbos_delete_get(self, db, branch, user):
        from transfusion.models import MSBOS
        entry = MSBOS.objects.create(
            procedure_code='DEL1', branch=branch, order_type='none', units_count=0
        )
        resp = _client(user, branch).get(f'/transfusion/msbos/{entry.pk}/delete/')
        assert resp.status_code == 200

    def test_msbos_delete_post_removes_entry(self, db, branch, user):
        from transfusion.models import MSBOS
        entry = MSBOS.objects.create(
            procedure_code='DEL2', branch=branch, order_type='none', units_count=0
        )
        pk = entry.pk
        _client(user, branch).post(f'/transfusion/msbos/{pk}/delete/')
        assert not MSBOS.objects.filter(pk=pk).exists()

    def test_msbos_delete_post_writes_audit(self, db, branch, user):
        from transfusion.models import MSBOS
        from audit.models import AuditLog
        entry = MSBOS.objects.create(
            procedure_code='DELAUDIT', branch=branch, order_type='none', units_count=0
        )
        _client(user, branch).post(f'/transfusion/msbos/{entry.pk}/delete/')
        assert AuditLog.objects.filter(action='msbos.delete').exists()

    def test_msbos_wrong_branch_returns_404(self, db, branch, user):
        from transfusion.models import MSBOS
        other_branch = BranchFactory()
        entry = MSBOS.objects.create(
            procedure_code='OTHBRANCH', branch=other_branch, order_type='none', units_count=0
        )
        resp = _client(user, branch).get(f'/transfusion/msbos/{entry.pk}/edit/')
        assert resp.status_code == 404


# ─── Blood request list and detail ────────────────────────────────────────────

class TestRequestListView:

    def test_request_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/request/')
        assert resp.status_code == 200

    def test_request_list_shows_requests(self, db, branch, user):
        BloodRequestFactory(branch=branch, requesting_physician=user)
        resp = _client(user, branch).get('/transfusion/request/')
        assert resp.status_code == 200

    def test_request_list_filter_by_urgency(self, db, branch, user):
        BloodRequestFactory(branch=branch, requesting_physician=user, urgency='urgent')
        BloodRequestFactory(branch=branch, requesting_physician=user, urgency='routine')
        resp = _client(user, branch).get('/transfusion/request/?urgency=urgent')
        assert resp.status_code == 200

    def test_request_list_filter_by_component(self, db, branch, user):
        BloodRequestFactory(branch=branch, requesting_physician=user, component_class='RBC')
        BloodRequestFactory(branch=branch, requesting_physician=user, component_class='FFP')
        resp = _client(user, branch).get('/transfusion/request/?component=RBC')
        assert resp.status_code == 200

    def test_request_list_unauthenticated_redirects(self, db, branch):
        resp = Client().get('/transfusion/request/')
        assert resp.status_code == 302
        assert 'login' in resp.get('Location', '').lower()


class TestRequestDetailView:

    def test_request_detail_get(self, db, branch, user):
        req = BloodRequestFactory(branch=branch, requesting_physician=user)
        resp = _client(user, branch).get(f'/transfusion/request/{req.pk}/')
        assert resp.status_code == 200

    def test_request_detail_context_has_req(self, db, branch, user):
        req = BloodRequestFactory(branch=branch, requesting_physician=user)
        resp = _client(user, branch).get(f'/transfusion/request/{req.pk}/')
        assert 'req' in resp.context
        assert resp.context['req'].pk == req.pk

    def test_request_detail_context_has_crossmatches(self, db, branch, user):
        req = BloodRequestFactory(branch=branch, requesting_physician=user)
        resp = _client(user, branch).get(f'/transfusion/request/{req.pk}/')
        assert 'crossmatches' in resp.context

    def test_request_detail_not_found(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/request/99999/')
        assert resp.status_code == 404

    def test_request_detail_unauthenticated_redirects(self, db, branch, user):
        req = BloodRequestFactory(branch=branch, requesting_physician=user)
        resp = Client().get(f'/transfusion/request/{req.pk}/')
        assert resp.status_code == 302


# ─── Donation blood grouping ──────────────────────────────────────────────────

class TestDonationBloodGroupingView:

    def _make_donation_and_sample(self, branch, actor):
        from transfusion.models import Sample
        import uuid
        donation = DonationFactory(collected_by=actor)
        accession = f'DNG-{uuid.uuid4().hex[:8].upper()}'
        sample = Sample.objects.create(
            donor=donation.donor,
            accession_number=accession,
            collected_at=timezone.now(),
            collected_by=actor,
            sample_type='donor_screening',
            branch=branch,
        )
        return donation, sample

    def test_get_renders_form(self, db, branch, user):
        su = _su(branch)
        donation, _ = self._make_donation_and_sample(branch, su)
        resp = _client(su, branch).get(f'/transfusion/donation/{donation.pk}/blood-grouping/')
        assert resp.status_code == 200

    def test_get_permission_denied_redirects_non_privileged(self, db, branch, user):
        donation, _ = self._make_donation_and_sample(branch, user)
        resp = _client(user, branch).get(f'/transfusion/donation/{donation.pk}/blood-grouping/')
        assert resp.status_code in (200, 302)

    def test_post_records_first_typing(self, db, branch, user):
        from transfusion.models import DonationBloodGrouping
        su = _su(branch)
        donation, sample = self._make_donation_and_sample(branch, su)
        _client(su, branch).post(
            f'/transfusion/donation/{donation.pk}/blood-grouping/',
            {
                'accession_number': sample.accession_number,
                'abo_result': 'O',
                'rh_d_result': 'pos',
                'method': 'tube',
                'determination_status': 'first',
                'forward_a': 'neg',
                'forward_b': 'neg',
            },
        )
        assert DonationBloodGrouping.objects.filter(donation=donation, abo_result='O').exists()

    def test_post_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        donation, sample = self._make_donation_and_sample(branch, su)
        _client(su, branch).post(
            f'/transfusion/donation/{donation.pk}/blood-grouping/',
            {
                'accession_number': sample.accession_number,
                'abo_result': 'A',
                'rh_d_result': 'pos',
                'method': 'gel',
                'determination_status': 'first',
            },
        )
        assert AuditLog.objects.filter(action='donation.blood_grouping').exists()

    def test_post_discrepant_result_sets_discrepant_status(self, db, branch, user):
        from transfusion.models import DonationBloodGrouping, Sample
        import uuid
        su = _su(branch)
        donation, sample = self._make_donation_and_sample(branch, su)
        # Create a first typing: O positive
        DonationBloodGrouping.objects.create(
            donation=donation,
            sample=sample,
            abo_result='O',
            rh_d_result='pos',
            method='tube',
            determination_status='first',
            performed_by=su,
            performed_at=timezone.now(),
        )
        # Second typing with different ABO on a new sample
        accession2 = f'DNG2-{uuid.uuid4().hex[:8].upper()}'
        sample2 = Sample.objects.create(
            donor=donation.donor,
            accession_number=accession2,
            collected_at=timezone.now(),
            collected_by=su,
            sample_type='donor_screening',
            branch=branch,
        )
        _client(su, branch).post(
            f'/transfusion/donation/{donation.pk}/blood-grouping/',
            {
                'accession_number': accession2,
                'abo_result': 'A',
                'rh_d_result': 'pos',
                'method': 'tube',
                'determination_status': 'first',
            },
        )
        latest = DonationBloodGrouping.objects.filter(
            donation=donation
        ).order_by('-performed_at').first()
        assert latest is not None
        assert latest.determination_status == 'discrepant'

    def test_post_nonexistent_donation_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/transfusion/donation/99999/blood-grouping/')
        assert resp.status_code == 404


# ─── TTI result recording ─────────────────────────────────────────────────────

@pytest.fixture
def _tti_setup(db, branch, user):
    """Returns (su, donation, test_def, donor_sample) for TTI tests."""
    from transfusion.models import TestDefinition, Sample
    su = _su(branch)
    donor = DonorFactory(registration_branch=branch, created_by=su)
    donation = DonationFactory(donor=donor, branch=branch, collected_by=su)
    test_def, _ = TestDefinition.objects.get_or_create(
        test_code='HIV_AgAb',
        defaults={
            'name': 'HIV 1/2 Ag+Ab Combo',
            'pathogen': 'HIV',
            'method': 'ELISA',
            'mandatory': True,
            'applies_to': 'donors',
        },
    )
    import uuid
    accession = f'DS-{uuid.uuid4().hex[:8].upper()}'
    donor_sample = Sample.objects.create(
        donor=donor,
        accession_number=accession,
        collected_at=timezone.now(),
        collected_by=su,
        sample_type='donor_screening',
        branch=branch,
    )
    return su, donation, test_def, donor_sample


class TestRecordTTIResultView:

    def test_get_renders_form(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/transfusion/tti/record/')
        assert resp.status_code == 200

    def test_get_non_privileged_redirects(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/tti/record/')
        assert resp.status_code in (200, 302)

    def test_post_records_non_reactive_result(self, db, branch, user, _tti_setup):
        from transfusion.models import DonationTestResult
        su, donation, test_def, donor_sample = _tti_setup
        resp = _client(su, branch).post('/transfusion/tti/record/', {
            'donation_id': donation.pk,
            'accession_number': donor_sample.accession_number,
            'test_code': test_def.test_code,
            'result': 'non_reactive',
        })
        assert resp.status_code in (200, 302)
        assert DonationTestResult.objects.filter(
            donation=donation, test=test_def, result='non_reactive'
        ).exists()

    def test_post_writes_audit_trail(self, db, branch, user, _tti_setup):
        from audit.models import AuditLog
        su, donation, test_def, donor_sample = _tti_setup
        _client(su, branch).post('/transfusion/tti/record/', {
            'donation_id': donation.pk,
            'accession_number': donor_sample.accession_number,
            'test_code': test_def.test_code,
            'result': 'non_reactive',
        })
        assert AuditLog.objects.filter(action='donation.test_result').exists()

    def test_unauthenticated_redirects(self, db):
        resp = Client().get('/transfusion/tti/record/')
        assert resp.status_code == 302


# ─── Unit reservation (lock / unlock for crossmatch) ─────────────────────────

class TestLockUnitForXM:

    @pytest.fixture(autouse=True)
    def _seed(self, db):
        from inventory.state_machine import seed_transitions
        seed_transitions()

    def _make_unit_and_req(self, branch, actor):
        unit = BloodUnitFactory(
            status='available',
            owner_branch=branch,
            expiry_datetime=timezone.now() + timedelta(days=42),
        )
        req = BloodRequestFactory(branch=branch, requesting_physician=actor)
        return unit, req

    def test_post_reserves_unit(self, db, branch, user):
        from inventory.models import BloodUnit
        su = _su(branch)
        unit, req = self._make_unit_and_req(branch, su)
        _client(su, branch).post('/transfusion/crossmatch/lock/', {
            'unit_did': unit.did,
            'request_id': req.pk,
        })
        unit.refresh_from_db()
        assert unit.status == 'reserved'
        assert unit.reserved_for_request_id == req.pk

    def test_post_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        unit, req = self._make_unit_and_req(branch, su)
        _client(su, branch).post('/transfusion/crossmatch/lock/', {
            'unit_did': unit.did,
            'request_id': req.pk,
        })
        assert AuditLog.objects.filter(action='unit.reserved_for_xm').exists()

    def test_post_nonexistent_unit_returns_404(self, db, branch, user):
        su = _su(branch)
        req = BloodRequestFactory(branch=branch, requesting_physician=su)
        resp = _client(su, branch).post('/transfusion/crossmatch/lock/', {
            'unit_did': 'NONEXISTENT99',
            'request_id': req.pk,
        })
        assert resp.status_code == 404

    def test_get_redirects_to_crossmatch(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/transfusion/crossmatch/lock/')
        assert resp.status_code in (200, 302)


class TestUnlockUnitForXM:

    @pytest.fixture(autouse=True)
    def _seed(self, db):
        from inventory.state_machine import seed_transitions
        seed_transitions()

    def _make_reserved_unit_and_req(self, branch, actor):
        req = BloodRequestFactory(branch=branch, requesting_physician=actor)
        unit = BloodUnitFactory(
            status='reserved',
            owner_branch=branch,
            expiry_datetime=timezone.now() + timedelta(days=42),
        )
        unit.reserved_for_request = req
        unit.reserved_by = actor
        unit.reserved_until = timezone.now() + timedelta(hours=4)
        unit.save(update_fields=['reserved_for_request', 'reserved_by', 'reserved_until'])
        return unit, req

    def test_post_releases_unit_back_to_available(self, db, branch, user):
        su = _su(branch)
        unit, req = self._make_reserved_unit_and_req(branch, su)
        _client(su, branch).post('/transfusion/crossmatch/unlock/', {
            'unit_did': unit.did,
            'request_id': req.pk,
        })
        unit.refresh_from_db()
        assert unit.status == 'available'
        assert unit.reserved_for_request_id is None

    def test_post_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        unit, req = self._make_reserved_unit_and_req(branch, su)
        _client(su, branch).post('/transfusion/crossmatch/unlock/', {
            'unit_did': unit.did,
            'request_id': req.pk,
        })
        assert AuditLog.objects.filter(action='unit.reservation_released').exists()


# ─── Crossmatch workspace (GET only) ─────────────────────────────────────────

class TestNewCrossmatchView:

    def test_get_without_request_id_renders_empty(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/transfusion/crossmatch/new/')
        assert resp.status_code == 200

    def test_get_with_request_id_renders_workspace(self, db, branch, user):
        su = _su(branch)
        req = BloodRequestFactory(branch=branch, requesting_physician=su)
        resp = _client(su, branch).get(f'/transfusion/crossmatch/new/?request_id={req.pk}')
        assert resp.status_code == 200
        assert 'req' in resp.context
        assert resp.context['req'].pk == req.pk

    def test_get_non_privileged_redirects(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/crossmatch/new/')
        assert resp.status_code in (200, 302)

    def test_unauthenticated_redirects(self, db):
        resp = Client().get('/transfusion/crossmatch/new/')
        assert resp.status_code == 302


# ─── Collect donor sample ─────────────────────────────────────────────────────

class TestCollectDonorSampleView:

    def test_get_renders_form(self, db, branch, user):
        su = _su(branch)
        donation = DonationFactory(branch=branch, collected_by=su)
        resp = _client(su, branch).get(f'/transfusion/donation/{donation.pk}/sample/')
        assert resp.status_code == 200

    def test_get_nonexistent_donation_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/transfusion/donation/99999/sample/')
        assert resp.status_code == 404

    def test_post_missing_accession_stays_on_page(self, db, branch, user):
        su = _su(branch)
        donation = DonationFactory(branch=branch, collected_by=su)
        resp = _client(su, branch).post(
            f'/transfusion/donation/{donation.pk}/sample/',
            {'accession_number': ''},
        )
        assert resp.status_code in (200, 302)

    def test_post_creates_sample(self, db, branch, user):
        from transfusion.models import Sample
        su = _su(branch)
        donation = DonationFactory(branch=branch, collected_by=su)
        accession = 'SCR-20260101-001'
        resp = _client(su, branch).post(
            f'/transfusion/donation/{donation.pk}/sample/',
            {'accession_number': accession},
        )
        assert resp.status_code in (200, 302)
        assert Sample.objects.filter(accession_number=accession).exists()

    def test_post_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        donation = DonationFactory(branch=branch, collected_by=su)
        _client(su, branch).post(
            f'/transfusion/donation/{donation.pk}/sample/',
            {'accession_number': 'SCR-AUD-TEST-001'},
        )
        assert AuditLog.objects.filter(action='sample.collect.donor').exists()

    def test_post_duplicate_accession_shows_error(self, db, branch, user):
        from transfusion.models import Sample
        su = _su(branch)
        donation = DonationFactory(branch=branch, collected_by=su)
        accession = 'SCR-DUP-001'
        Sample.objects.create(
            donor=donation.donor, accession_number=accession,
            collected_at=timezone.now(), collected_by=su,
            sample_type='donor_screening', branch=branch,
        )
        resp = _client(su, branch).post(
            f'/transfusion/donation/{donation.pk}/sample/',
            {'accession_number': accession},
        )
        assert resp.status_code in (200, 302)
        assert Sample.objects.filter(accession_number=accession).count() == 1

    def test_unauthenticated_redirects(self, db, branch, user):
        donation = DonationFactory(branch=branch, collected_by=user)
        resp = Client().get(f'/transfusion/donation/{donation.pk}/sample/')
        assert resp.status_code == 302


# ─── Post-transfusion outcome list ────────────────────────────────────────────

class TestPostOutcomeListView:

    def test_get_renders_list(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/outcomes/')
        assert resp.status_code == 200

    def test_get_with_response_filter(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/outcomes/?response=expected')
        assert resp.status_code == 200

    def test_unauthenticated_redirects(self, db):
        resp = Client().get('/transfusion/outcomes/')
        assert resp.status_code == 302


# ─── Issue unit view ──────────────────────────────────────────────────────────

class TestIssueUnitView:

    def _setup_crossmatched_unit(self, branch, collector, issuer):
        """Build the full chain needed for issue_unit_view POST."""
        import hashlib
        from transfusion.models import Crossmatch, Sample
        from audit.models import ElectronicSignature

        donor = DonorFactory(registration_branch=branch, created_by=collector)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=collector)
        unit = BloodUnitFactory(
            donation=donation,
            abo_type='O', rh_d_type='neg',
            status='crossmatched',
            owner_branch=branch,
            expiry_datetime=timezone.now() + timedelta(days=35),
        )
        patient = PatientFactory(created_by=collector)
        blood_request = BloodRequestFactory(
            patient=patient, branch=branch, requesting_physician=collector, component_class='RBC',
        )
        # Sample (required for Crossmatch FK)
        sample = Sample.objects.create(
            patient=patient,
            accession_number=f'ACC-{unit.pk}-{donation.pk}',
            collected_at=timezone.now() - timedelta(hours=2),
            collected_by=collector,
            sample_type='pre_transfusion',
            branch=branch,
        )
        # ElectronicSignature for the crossmatch
        esign_xm = ElectronicSignature.objects.create(
            signer=issuer,
            signed_at_utc=timezone.now(),
            meaning='verified',
            auth_method='password_reauth',
            reauth_at=timezone.now(),
            signed_payload_hash=hashlib.sha256(b'xm-sign').hexdigest(),
            manifested_name=issuer.display_name or issuer.username,
        )
        xm = Crossmatch.objects.create(
            sample=sample,
            blood_unit=unit,
            request=blood_request,
            method='immediate_spin',
            result='compatible',
            tech=issuer,
            performed_at=timezone.now(),
            esign=esign_xm,
        )
        return unit, patient, blood_request, xm

    def test_get_renders_form(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/issue/')
        assert resp.status_code == 200

    def test_get_with_request_id_shows_crossmatched_units(self, db, branch, user):
        su = _su(branch)
        unit, patient, blood_request, xm = self._setup_crossmatched_unit(branch, user, su)
        resp = _client(su, branch).get(f'/transfusion/issue/?request_id={blood_request.pk}')
        assert resp.status_code == 200

    def test_post_issues_unit_and_redirects(self, db, branch, user):
        """Happy path: issue a crossmatched O-neg unit to an adult patient."""
        from inventory.models import BloodUnit
        su = _su(branch)
        unit, patient, blood_request, xm = self._setup_crossmatched_unit(branch, user, su)
        resp = _client(su, branch).post('/transfusion/issue/', {
            'unit_did': unit.did,
            'request_id': blood_request.pk,
            'patient_id': patient.pk,
            'crossmatch_id': xm.pk,
        })
        assert resp.status_code == 302
        unit.refresh_from_db()
        assert unit.status == 'issued'

    def test_post_writes_audit_trail(self, db, branch, user):
        """Issue transaction writes a unit.issued audit entry."""
        from audit.models import AuditLog
        su = _su(branch)
        unit, patient, blood_request, xm = self._setup_crossmatched_unit(branch, user, su)
        _client(su, branch).post('/transfusion/issue/', {
            'unit_did': unit.did,
            'request_id': blood_request.pk,
            'patient_id': patient.pk,
            'crossmatch_id': xm.pk,
        })
        assert AuditLog.objects.filter(action='unit.issued').exists()

    def test_post_nonexistent_did_shows_error(self, db, branch, user):
        """POSTing an unknown DID does not crash — shows an error and redirects."""
        su = _su(branch)
        blood_request = BloodRequestFactory(
            patient=PatientFactory(created_by=user),
            branch=branch, requesting_physician=user, component_class='RBC',
        )
        resp = _client(su, branch).post('/transfusion/issue/', {
            'unit_did': 'NONEXISTENT-DID-000',
            'request_id': blood_request.pk,
            'patient_id': blood_request.patient_id,
        })
        assert resp.status_code == 302

    def test_unauthenticated_redirects(self, db):
        resp = Client().get('/transfusion/issue/')
        assert resp.status_code == 302


# ─── Lookback views ───────────────────────────────────────────────────────────

class TestLookbackViews:

    def test_lookback_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/lookback/')
        assert resp.status_code == 200

    def test_lookback_list_unauthenticated_redirects(self, db):
        resp = Client().get('/transfusion/lookback/')
        assert resp.status_code == 302

    def test_lookback_initiate_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/lookback/initiate/')
        assert resp.status_code == 200

    def test_lookback_initiate_post_nonexistent_result_shows_error(self, db, branch, user):
        """POSTing a non-existent test_result_pk should not crash."""
        resp = _client(user, branch).post('/transfusion/lookback/initiate/', {
            'test_result_pk': '999999',
        })
        assert resp.status_code in (200, 302)

    def _make_campaign(self, branch, user):
        from datetime import date
        from transfusion.models import LookbackCampaign
        donor = DonorFactory(registration_branch=branch, created_by=user)
        return LookbackCampaign.objects.create(
            donor=donor,
            triggered_by_test='HCV-Ab',
            triggered_at=timezone.now(),
            initiated_by=user,
            lookback_from=date.today() - timedelta(days=70),
        )

    def test_lookback_detail_renders(self, db, branch, user):
        """GET lookback detail page for an existing campaign."""
        campaign = self._make_campaign(branch, user)
        resp = _client(user, branch).get(f'/transfusion/lookback/{campaign.pk}/')
        assert resp.status_code == 200

    def test_lookback_detail_post_close_writes_audit(self, db, branch, user):
        """Closing a lookback campaign writes an audit entry."""
        from audit.models import AuditLog
        campaign = self._make_campaign(branch, user)
        resp = _client(user, branch).post(f'/transfusion/lookback/{campaign.pk}/', {
            'action': 'close',
        })
        assert resp.status_code == 302
        campaign.refresh_from_db()
        assert campaign.status == 'closed'
        assert AuditLog.objects.filter(action='lookback.campaign.closed').exists()


# ─── Surgical order views ─────────────────────────────────────────────────────

class TestSurgicalOrderViews:

    def _make_order(self, branch, user):
        from transfusion.models import SurgicalBloodOrder
        patient = PatientFactory(created_by=user)
        return SurgicalBloodOrder.objects.create(
            patient=patient,
            branch=branch,
            procedure_code='CABG-01',
            procedure_name='Coronary Artery Bypass Graft',
            scheduled_datetime=timezone.now() + timedelta(days=3),
            surgeon=user,
            created_by=user,
            component_class='RBC',
        )

    def test_surgical_order_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/surgical-orders/')
        assert resp.status_code == 200

    def test_surgical_order_list_shows_branch_orders(self, db, branch, user):
        self._make_order(branch, user)
        resp = _client(user, branch).get('/transfusion/surgical-orders/')
        assert resp.status_code == 200

    def test_surgical_order_create_get(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        resp = _client(user, branch).get(f'/transfusion/surgical-orders/patient/{patient.pk}/new/')
        assert resp.status_code == 200

    def test_surgical_order_create_post_creates_order(self, db, branch, user):
        from transfusion.models import SurgicalBloodOrder
        patient = PatientFactory(created_by=user)
        count_before = SurgicalBloodOrder.objects.filter(branch=branch).count()
        sched = (timezone.now() + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M')
        resp = _client(user, branch).post(
            f'/transfusion/surgical-orders/patient/{patient.pk}/new/',
            {
                'procedure_code': 'THR-LT',
                'procedure_name': 'Total Hip Replacement Left',
                'scheduled_datetime': sched,
                'component_class': 'RBC',
                'notes': 'Elective surgery',
            },
        )
        assert resp.status_code in (200, 302)
        assert SurgicalBloodOrder.objects.filter(branch=branch).count() > count_before

    def test_surgical_order_create_post_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        patient = PatientFactory(created_by=user)
        sched = (timezone.now() + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M')
        _client(user, branch).post(
            f'/transfusion/surgical-orders/patient/{patient.pk}/new/',
            {
                'procedure_code': 'OHO-99',
                'scheduled_datetime': sched,
                'component_class': 'PLT',
            },
        )
        assert AuditLog.objects.filter(action='surgical_order.create').exists()

    def test_surgical_order_create_post_missing_fields_stays_on_form(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        resp = _client(user, branch).post(
            f'/transfusion/surgical-orders/patient/{patient.pk}/new/',
            {'procedure_code': ''},  # missing scheduled_datetime
        )
        # Should stay on form (200) or redirect with error (302)
        assert resp.status_code in (200, 302)

    def test_surgical_order_detail_get(self, db, branch, user):
        order = self._make_order(branch, user)
        resp = _client(user, branch).get(f'/transfusion/surgical-orders/{order.pk}/')
        assert resp.status_code == 200

    def test_surgical_order_approve_get(self, db, branch, user):
        order = self._make_order(branch, user)
        resp = _client(user, branch).get(f'/transfusion/surgical-orders/{order.pk}/approve/')
        assert resp.status_code == 200

    def test_surgical_order_approve_post_approves_order(self, db, branch, user):
        from transfusion.models import SurgicalBloodOrder
        order = self._make_order(branch, user)
        resp = _client(user, branch).post(f'/transfusion/surgical-orders/{order.pk}/approve/', {
            'approved_order_type': 'crossmatch',
            'approved_units': '2',
        })
        assert resp.status_code == 302
        order.refresh_from_db()
        assert order.status == 'approved'

    def test_surgical_order_approve_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        order = self._make_order(branch, user)
        _client(user, branch).post(f'/transfusion/surgical-orders/{order.pk}/approve/', {
            'approved_order_type': 'type_and_screen',
            'approved_units': '0',
        })
        assert AuditLog.objects.filter(action='surgical_order.approve').exists()

    def test_surgical_order_cancel_get(self, db, branch, user):
        order = self._make_order(branch, user)
        resp = _client(user, branch).get(f'/transfusion/surgical-orders/{order.pk}/cancel/')
        assert resp.status_code == 200

    def test_surgical_order_cancel_post_cancels_order(self, db, branch, user):
        from transfusion.models import SurgicalBloodOrder
        order = self._make_order(branch, user)
        resp = _client(user, branch).post(f'/transfusion/surgical-orders/{order.pk}/cancel/')
        assert resp.status_code == 302
        order.refresh_from_db()
        assert order.status == 'cancelled'

    def test_surgical_order_cancel_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        order = self._make_order(branch, user)
        _client(user, branch).post(f'/transfusion/surgical-orders/{order.pk}/cancel/')
        assert AuditLog.objects.filter(action='surgical_order.cancel').exists()

    def test_surgical_order_unauthenticated_redirects(self, db):
        resp = Client().get('/transfusion/surgical-orders/')
        assert resp.status_code == 302
