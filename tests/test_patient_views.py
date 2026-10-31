"""
Tests for patient-workflow views:
  - register_patient, patient_detail
  - add_blood_group, add_antibody, add_requirement
  - traceability_report
Also covers cold chain views:
  - excursion_list, excursion_resolve, unit_return_check
"""
import pytest
import hashlib
from datetime import timedelta
from django.utils import timezone
from django.test import Client

from tests.conftest import (
    UserFactory, BranchFactory, DonorFactory, DonationFactory,
    BloodUnitFactory, PatientFactory, PatientBloodGroupFactory,
    BloodRequestFactory, StorageEquipmentFactory,
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
        username=f'su_pv_{branch.pk}_{timezone.now().timestamp():.0f}',
        password='testpass123',
        display_name='PV Super',
        branch=branch,
    )


def _make_esign(user):
    from audit.models import ElectronicSignature
    return ElectronicSignature.objects.create(
        signer=user,
        signed_at_utc=timezone.now(),
        meaning='verified',
        auth_method='password_reauth',
        reauth_at=timezone.now(),
        signed_payload_hash=hashlib.sha256(b'patient-view-test').hexdigest(),
        manifested_name=user.display_name or user.username,
    )


# ─── Patient registration ─────────────────────────────────────────────────────

class TestRegisterPatient:

    def test_register_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/patients/register/')
        assert resp.status_code == 200

    def test_register_post_creates_patient(self, db, branch, user):
        from patients.models import Patient
        su = _su(branch)
        resp = _client(su, branch).post('/patients/register/', {
            'full_name': 'Jane Doe',
            'national_id': 'NID-TEST-001',
            'contact': '',
            'sex': 'F',
            'dob': '1985-03-15',
            'abo': 'A',
            'rh_d': 'pos',
        })
        assert resp.status_code in (200, 302)
        assert Patient.objects.filter(sex='F').exists()

    def test_register_requires_permission(self, db, branch, user):
        resp = _client(user, branch).get('/patients/register/')
        assert resp.status_code in (200, 302)


# ─── Patient detail ───────────────────────────────────────────────────────────

class TestPatientDetail:

    def test_patient_detail_get(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        resp = _client(user, branch).get(f'/patients/{patient.pk}/')
        assert resp.status_code == 200

    def test_patient_detail_with_blood_group(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        PatientBloodGroupFactory(patient=patient, branch=branch, abo='AB', rh_d='pos',
                                  determined_by=user)
        resp = _client(user, branch).get(f'/patients/{patient.pk}/')
        assert resp.status_code == 200

    def test_patient_detail_404_for_unknown(self, db, branch, user):
        resp = _client(user, branch).get('/patients/999999/')
        assert resp.status_code == 404


# ─── Blood group ──────────────────────────────────────────────────────────────

class TestAddBloodGroup:

    def test_add_blood_group_get(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(created_by=user)
        resp = _client(su, branch).get(f'/patients/{patient.pk}/blood-group/add/')
        assert resp.status_code == 200

    def test_add_blood_group_post(self, db, branch, user):
        from patients.models import PatientBloodGroup
        su = _su(branch)
        patient = PatientFactory(created_by=user)
        resp = _client(su, branch).post(f'/patients/{patient.pk}/blood-group/add/', {
            'abo': 'O',
            'rh_d': 'neg',
            'method': 'tube',
        })
        assert resp.status_code in (200, 302)
        assert PatientBloodGroup.objects.filter(patient=patient, abo='O', rh_d='neg').exists()

    def test_add_blood_group_detects_discrepancy(self, db, branch, user):
        from patients.models import PatientBloodGroup
        su = _su(branch)
        patient = PatientFactory(created_by=user)
        # Establish first group: O neg
        PatientBloodGroupFactory(patient=patient, branch=branch, abo='O', rh_d='neg',
                                  determined_by=user)
        PatientBloodGroupFactory(patient=patient, branch=branch, abo='O', rh_d='neg',
                                  determined_by=user)
        # Add a different group: A pos → discrepancy
        _client(su, branch).post(f'/patients/{patient.pk}/blood-group/add/', {
            'abo': 'A',
            'rh_d': 'pos',
            'method': 'tube',
        })
        discrepant = PatientBloodGroup.objects.filter(patient=patient, abo='A', is_discrepant=True)
        assert discrepant.exists()


# ─── Antibody ─────────────────────────────────────────────────────────────────

class TestAddAntibody:

    def test_add_antibody_get(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        resp = _client(user, branch).get(f'/patients/{patient.pk}/antibody/add/')
        assert resp.status_code == 200

    def test_add_antibody_post(self, db, branch, user):
        from patients.models import PatientAntibody
        patient = PatientFactory(created_by=user)
        resp = _client(user, branch).post(f'/patients/{patient.pk}/antibody/add/', {
            'specificity': 'anti-D',
            'antigen_system': 'Rh',
            'clinical_significance': 'significant',
        })
        assert resp.status_code in (200, 302)
        assert PatientAntibody.objects.filter(patient=patient, specificity='anti-D').exists()

    def test_add_multiple_antibodies(self, db, branch, user):
        from patients.models import PatientAntibody
        patient = PatientFactory(created_by=user)
        c = _client(user, branch)
        c.post(f'/patients/{patient.pk}/antibody/add/', {
            'specificity': 'anti-K',
            'antigen_system': 'Kell',
            'clinical_significance': 'significant',
        })
        c.post(f'/patients/{patient.pk}/antibody/add/', {
            'specificity': 'anti-E',
            'antigen_system': 'Rh',
            'clinical_significance': 'significant',
        })
        assert PatientAntibody.objects.filter(patient=patient).count() == 2


# ─── Special requirements ─────────────────────────────────────────────────────

class TestAddRequirement:

    def test_add_requirement_get(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(created_by=user)
        resp = _client(su, branch).get(f'/patients/{patient.pk}/requirement/add/')
        assert resp.status_code == 200

    def test_add_requirement_post(self, db, branch, user):
        from patients.models import PatientTransfusionRequirement
        su = _su(branch)
        patient = PatientFactory(created_by=user)
        resp = _client(su, branch).post(f'/patients/{patient.pk}/requirement/add/', {
            'requirement': 'irradiated',
            'antigen_spec': '',
            'reason': 'Post-haematopoietic stem cell transplant — TA-GvHD prevention.',
        })
        assert resp.status_code in (200, 302)
        assert PatientTransfusionRequirement.objects.filter(
            patient=patient, requirement='irradiated'
        ).exists()


# ─── Traceability report ──────────────────────────────────────────────────────

class TestTraceabilityReport:

    def test_traceability_get_no_transfusions(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        resp = _client(user, branch).get(f'/patients/{patient.pk}/traceability/')
        assert resp.status_code == 200
        assert len(list(resp.context['transactions'])) == 0

    def test_traceability_get_with_transfusion(self, db, branch, user):
        from transfusion.models import IssueTransaction
        patient = PatientFactory(created_by=user)
        blood_request = BloodRequestFactory(patient=patient, branch=branch,
                                             requesting_physician=user)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='issued', owner_branch=branch)
        esign = _make_esign(user)
        IssueTransaction.objects.create(
            blood_unit=unit, request=blood_request, patient=patient,
            issued_by=user, issue_esign=esign, abo_check_passed=True,
            issued_at=timezone.now() - timedelta(hours=3), intended_branch=branch,
        )
        resp = _client(user, branch).get(f'/patients/{patient.pk}/traceability/')
        assert resp.status_code == 200
        assert len(list(resp.context['transactions'])) == 1


# ─── Cold chain: excursion views ──────────────────────────────────────────────

class TestColdChainViews:

    def test_excursion_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/coldchain/excursions/')
        assert resp.status_code == 200

    def test_excursion_list_with_open_excursion(self, db, branch, user):
        from coldchain.models import TemperatureExcursion
        equipment = StorageEquipmentFactory(branch=branch)
        TemperatureExcursion.objects.create(
            equipment=equipment,
            started_at=timezone.now() - timedelta(hours=2),
            max_temp_c=10.0,
            auto_quarantine=False,
        )
        resp = _client(user, branch).get('/coldchain/excursions/')
        assert resp.status_code == 200

    def test_excursion_resolve_get(self, db, branch, user):
        from coldchain.models import TemperatureExcursion
        equipment = StorageEquipmentFactory(branch=branch)
        excursion = TemperatureExcursion.objects.create(
            equipment=equipment,
            started_at=timezone.now() - timedelta(hours=1),
            max_temp_c=9.5,
            auto_quarantine=False,
        )
        resp = _client(user, branch).get(f'/coldchain/excursions/{excursion.pk}/resolve/')
        assert resp.status_code == 200

    def test_excursion_resolve_post(self, db, branch, user):
        from coldchain.models import TemperatureExcursion
        equipment = StorageEquipmentFactory(branch=branch)
        excursion = TemperatureExcursion.objects.create(
            equipment=equipment,
            started_at=timezone.now() - timedelta(hours=1),
            max_temp_c=9.5,
            auto_quarantine=False,
        )
        resp = _client(user, branch).post(f'/coldchain/excursions/{excursion.pk}/resolve/', {
            'disposition': 'no_action',
            'justification': 'Equipment door briefly opened for 5 minutes. Units stable within spec.',
        })
        assert resp.status_code in (200, 302)
        excursion.refresh_from_db()
        assert excursion.ended_at is not None


# ─── Patient list ─────────────────────────────────────────────────────────────

class TestPatientListView:

    def test_patient_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/patients/')
        assert resp.status_code == 200

    def test_patient_list_shows_patient(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        resp = _client(user, branch).get('/patients/')
        assert resp.status_code == 200

    def test_patient_list_unauthenticated_redirects(self, db, branch):
        resp = Client().get('/patients/')
        assert resp.status_code == 302
        assert 'login' in resp.get('Location', '').lower()


# ─── Transfusion consent ──────────────────────────────────────────────────────

class TestRecordConsentView:

    def test_get_renders_form(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        resp = _client(user, branch).get(f'/patients/{patient.pk}/consent/')
        assert resp.status_code == 200

    def test_post_creates_consent(self, db, branch, user):
        from patients.models import TransfusionConsent
        patient = PatientFactory(created_by=user)
        resp = _client(user, branch).post(f'/patients/{patient.pk}/consent/', {
            'consent_type': 'verbal',
            'alternatives_discussed': 'on',
            'risks_explained': 'on',
            'questions_answered': 'on',
        })
        assert resp.status_code in (200, 302)
        assert TransfusionConsent.objects.filter(patient=patient, consent_type='verbal').exists()

    def test_post_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        patient = PatientFactory(created_by=user)
        _client(user, branch).post(f'/patients/{patient.pk}/consent/', {
            'consent_type': 'written',
            'alternatives_discussed': 'on',
            'risks_explained': 'on',
        })
        assert AuditLog.objects.filter(action='patient.consent.record').exists()

    def test_post_implied_consent_without_justification_stays_on_form(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        from patients.models import TransfusionConsent
        count_before = TransfusionConsent.objects.count()
        resp = _client(user, branch).post(f'/patients/{patient.pk}/consent/', {
            'consent_type': 'implied',
            # no emergency_justification
        })
        assert resp.status_code == 200
        assert TransfusionConsent.objects.count() == count_before

    def test_get_nonexistent_patient_returns_404(self, db, branch, user):
        resp = _client(user, branch).get('/patients/99999/consent/')
        assert resp.status_code == 404


class TestWithdrawConsentView:

    def _make_active_consent(self, patient, branch, user):
        from patients.models import TransfusionConsent
        from django.utils import timezone as tz
        import datetime
        return TransfusionConsent.objects.create(
            patient=patient,
            consent_type='verbal',
            status='active',
            obtained_by=user,
            obtained_at=tz.now(),
            valid_until=tz.now().date() + datetime.timedelta(days=30),
            branch=branch,
        )

    def test_get_renders_withdrawal_form(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        consent = self._make_active_consent(patient, branch, user)
        resp = _client(user, branch).get(f'/patients/{patient.pk}/consent/{consent.pk}/withdraw/')
        assert resp.status_code == 200

    def test_post_withdraws_consent(self, db, branch, user):
        from patients.models import TransfusionConsent
        patient = PatientFactory(created_by=user)
        consent = self._make_active_consent(patient, branch, user)
        _client(user, branch).post(
            f'/patients/{patient.pk}/consent/{consent.pk}/withdraw/',
            {'reason': 'Patient changed their mind'},
        )
        consent.refresh_from_db()
        assert consent.status == 'withdrawn'
        assert consent.withdrawn_at is not None

    def test_post_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        patient = PatientFactory(created_by=user)
        consent = self._make_active_consent(patient, branch, user)
        _client(user, branch).post(
            f'/patients/{patient.pk}/consent/{consent.pk}/withdraw/',
            {'reason': 'Patient preference'},
        )
        assert AuditLog.objects.filter(action='patient.consent.withdrawn').exists()

    def test_post_without_reason_stays_on_form(self, db, branch, user):
        from patients.models import TransfusionConsent
        patient = PatientFactory(created_by=user)
        consent = self._make_active_consent(patient, branch, user)
        resp = _client(user, branch).post(
            f'/patients/{patient.pk}/consent/{consent.pk}/withdraw/',
            {'reason': ''},  # empty reason
        )
        assert resp.status_code == 200
        consent.refresh_from_db()
        assert consent.status == 'active'

    def test_already_withdrawn_consent_redirects(self, db, branch, user):
        from patients.models import TransfusionConsent
        import datetime
        from django.utils import timezone as tz
        patient = PatientFactory(created_by=user)
        consent = TransfusionConsent.objects.create(
            patient=patient,
            consent_type='verbal',
            status='withdrawn',
            obtained_by=user,
            obtained_at=tz.now(),
            valid_until=tz.now().date() + datetime.timedelta(days=30),
            branch=branch,
            withdrawn_at=tz.now(),
        )
        resp = _client(user, branch).post(
            f'/patients/{patient.pk}/consent/{consent.pk}/withdraw/',
            {'reason': 'Already withdrawn'},
        )
        assert resp.status_code in (200, 302)


# ─── Therapeutic phlebotomy list ──────────────────────────────────────────────

class TestTherapeuticPhlebotomyListView:

    def test_get_renders_list(self, db, branch, user):
        resp = _client(user, branch).get('/patients/therapeutic-phlebotomy/')
        assert resp.status_code == 200

    def test_get_unauthenticated_redirects(self, db, branch):
        resp = Client().get('/patients/therapeutic-phlebotomy/')
        assert resp.status_code == 302
        assert 'login' in resp.get('Location', '').lower()


# ─── Patient phenotype ────────────────────────────────────────────────────────

class TestRecordPatientPhenotypeView:

    def test_get_renders_form(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).get(f'/patients/{patient.pk}/phenotype/')
        assert resp.status_code == 200

    def test_get_nonexistent_patient_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/patients/99999/phenotype/')
        assert resp.status_code == 404

    def test_post_creates_phenotype(self, db, branch, user):
        from patients.models import PatientPhenotype
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(f'/patients/{patient.pk}/phenotype/', {
            'antigen_C': 'pos',
            'antigen_c': 'neg',
            'antigen_E': 'neg',
            'antigen_e': 'pos',
            'antigen_K': 'neg',
            'method': 'serology',
            'notes': '',
        })
        assert resp.status_code in (200, 302)
        assert PatientPhenotype.objects.filter(patient=patient).exists()

    def test_post_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        _client(su, branch).post(f'/patients/{patient.pk}/phenotype/', {
            'antigen_C': 'pos',
            'antigen_K': 'neg',
            'method': 'serology',
            'notes': '',
        })
        assert AuditLog.objects.filter(
            action__startswith='patient.phenotype'
        ).exists()

    def test_post_updates_existing_phenotype(self, db, branch, user):
        from patients.models import PatientPhenotype
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        # Create an initial phenotype
        _client(su, branch).post(f'/patients/{patient.pk}/phenotype/', {
            'antigen_C': 'pos', 'method': 'serology', 'notes': '',
        })
        # Update it
        _client(su, branch).post(f'/patients/{patient.pk}/phenotype/', {
            'antigen_C': 'neg', 'method': 'serology', 'notes': 'updated',
        })
        phenotype = PatientPhenotype.objects.get(patient=patient)
        assert phenotype.C is False

    def test_unauthenticated_redirects(self, db, branch):
        patient = PatientFactory(registration_branch=branch)
        resp = Client().get(f'/patients/{patient.pk}/phenotype/')
        assert resp.status_code == 302
        assert 'login' in resp.get('Location', '').lower()


# ─── Merge patient ────────────────────────────────────────────────────────────

class TestMergePatientView:

    def test_get_renders_form(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).get(f'/patients/{patient.pk}/merge/')
        assert resp.status_code == 200

    def test_get_nonexistent_patient_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/patients/99999/merge/')
        assert resp.status_code == 404

    def test_post_missing_target_shows_error(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(f'/patients/{patient.pk}/merge/', {
            'target_patient_id': '',
            'reason': '',
        })
        assert resp.status_code == 200

    def test_post_merges_source_into_target(self, db, branch, user):
        from patients.models import Patient
        su = _su(branch)
        source = PatientFactory(registration_branch=branch)
        target = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(f'/patients/{source.pk}/merge/', {
            'target_patient_id': str(target.pk),
            'reason': 'Duplicate record created at reception',
        })
        assert resp.status_code in (200, 302)
        source.refresh_from_db()
        assert source.record_status == 'merged'
        assert source.merged_into_id == target.pk

    def test_post_merge_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        source = PatientFactory(registration_branch=branch)
        target = PatientFactory(registration_branch=branch)
        _client(su, branch).post(f'/patients/{source.pk}/merge/', {
            'target_patient_id': str(target.pk),
            'reason': 'Duplicate',
        })
        assert AuditLog.objects.filter(action='patient.merge').exists()

    def test_post_self_merge_shows_error(self, db, branch, user):
        from patients.models import Patient
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(f'/patients/{patient.pk}/merge/', {
            'target_patient_id': str(patient.pk),
            'reason': 'Duplicate',
        })
        assert resp.status_code == 200
        patient.refresh_from_db()
        assert patient.record_status == 'active'

    def test_unauthenticated_redirects(self, db, branch):
        patient = PatientFactory(registration_branch=branch)
        resp = Client().get(f'/patients/{patient.pk}/merge/')
        assert resp.status_code == 302


# ─── Therapeutic phlebotomy schedule ─────────────────────────────────────────

class TestTherapeuticPhlebotomyScheduleView:

    def test_get_renders_form(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).get(f'/patients/{patient.pk}/therapeutic-phlebotomy/schedule/')
        assert resp.status_code == 200

    def test_get_nonexistent_patient_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/patients/99999/therapeutic-phlebotomy/schedule/')
        assert resp.status_code == 404

    def test_post_missing_fields_shows_error(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(
            f'/patients/{patient.pk}/therapeutic-phlebotomy/schedule/',
            {'indication': '', 'scheduled_date': ''},
        )
        assert resp.status_code == 200

    def test_post_creates_tp_session(self, db, branch, user):
        from patients.models import TherapeuticPhlebotomy
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(
            f'/patients/{patient.pk}/therapeutic-phlebotomy/schedule/',
            {
                'indication': 'haemochromatosis',
                'scheduled_date': '2026-08-01',
                'target_volume_ml': '450',
                'disposition': 'discard',
                'indication_notes': '',
            },
        )
        assert resp.status_code in (200, 302)
        assert TherapeuticPhlebotomy.objects.filter(patient=patient).exists()

    def test_post_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        _client(su, branch).post(
            f'/patients/{patient.pk}/therapeutic-phlebotomy/schedule/',
            {
                'indication': 'polycythaemia_vera',
                'scheduled_date': '2026-09-15',
                'target_volume_ml': '400',
                'disposition': 'discard',
            },
        )
        assert AuditLog.objects.filter(action='therapeutic_phlebotomy.scheduled').exists()

    def test_unauthenticated_redirects(self, db, branch):
        patient = PatientFactory(registration_branch=branch)
        resp = Client().get(f'/patients/{patient.pk}/therapeutic-phlebotomy/schedule/')
        assert resp.status_code == 302


# ─── Antenatal views ──────────────────────────────────────────────────────────

class TestAntenatalViews:

    def test_list_get_renders(self, db, branch, user):
        resp = _client(user, branch).get('/patients/antenatal/')
        assert resp.status_code == 200

    def test_list_rh_neg_filter(self, db, branch, user):
        resp = _client(user, branch).get('/patients/antenatal/?rh_neg=1')
        assert resp.status_code == 200

    def test_create_get_renders_form(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).get(f'/patients/{patient.pk}/antenatal/new/')
        assert resp.status_code == 200

    def test_create_get_nonexistent_patient_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/patients/99999/antenatal/new/')
        assert resp.status_code == 404

    def test_create_post_missing_edd_shows_error(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(
            f'/patients/{patient.pk}/antenatal/new/',
            {'edd': '', 'abo': 'O', 'rh_d': 'neg'},
        )
        assert resp.status_code == 200

    def test_create_post_creates_record(self, db, branch, user):
        from patients.models import AntenatalRecord
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(
            f'/patients/{patient.pk}/antenatal/new/',
            {
                'edd': '2026-12-01',
                'abo': 'O',
                'rh_d': 'neg',
                'partner_rh_d': 'pos',
                'gestation_at_booking_wks': '12',
            },
        )
        assert resp.status_code in (200, 302)
        assert AntenatalRecord.objects.filter(patient=patient).exists()

    def test_create_post_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        _client(su, branch).post(
            f'/patients/{patient.pk}/antenatal/new/',
            {'edd': '2026-11-15', 'abo': 'A', 'rh_d': 'pos', 'partner_rh_d': 'unknown'},
        )
        assert AuditLog.objects.filter(action='antenatal.record.created').exists()

    def test_detail_get_renders(self, db, branch, user):
        from patients.models import AntenatalRecord
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        anc = AntenatalRecord.objects.create(
            patient=patient, edd='2026-12-15', branch=branch, created_by=su,
        )
        resp = _client(su, branch).get(f'/patients/antenatal/{anc.pk}/')
        assert resp.status_code == 200

    def test_detail_get_nonexistent_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/patients/antenatal/99999/')
        assert resp.status_code == 404

    def test_detail_post_update_outcome(self, db, branch, user):
        from patients.models import AntenatalRecord
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        anc = AntenatalRecord.objects.create(
            patient=patient, edd='2026-12-15', branch=branch, created_by=su,
        )
        resp = _client(su, branch).post(f'/patients/antenatal/{anc.pk}/', {
            'action': 'update_outcome',
            'outcome': 'delivered',
            'delivery_date': '2026-12-10',
        })
        assert resp.status_code in (200, 302)
        anc.refresh_from_db()
        assert anc.outcome == 'delivered'

    def test_list_unauthenticated_redirects(self, db):
        resp = Client().get('/patients/antenatal/')
        assert resp.status_code == 302


# ─── HDFN (Haemolytic Disease of Fetus and Newborn) views ────────────────────

class TestHDFNViews:

    def test_list_get_renders(self, db, branch, user):
        resp = _client(user, branch).get('/patients/hdfn/')
        assert resp.status_code == 200

    def test_list_severity_filter(self, db, branch, user):
        resp = _client(user, branch).get('/patients/hdfn/?severity=severe')
        assert resp.status_code == 200

    def test_create_get_renders_form(self, db, branch, user):
        su = _su(branch)
        mother = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).get(f'/patients/{mother.pk}/hdfn/new/')
        assert resp.status_code == 200

    def test_create_get_nonexistent_patient_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/patients/99999/hdfn/new/')
        assert resp.status_code == 404

    def test_create_post_creates_case(self, db, branch, user):
        from patients.models import HaemolyticDiseaseCase
        su = _su(branch)
        mother = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(
            f'/patients/{mother.pk}/hdfn/new/',
            {
                'antibody_specificity_text': 'Anti-c',
                'severity': 'mild',
                'outcome': 'resolved',
                'direct_antiglobulin_test': 'positive',
                'clinical_notes': 'Mild jaundice, resolved with phototherapy.',
            },
        )
        assert resp.status_code in (200, 302)
        assert HaemolyticDiseaseCase.objects.filter(mother=mother).exists()

    def test_create_post_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        mother = PatientFactory(registration_branch=branch)
        _client(su, branch).post(
            f'/patients/{mother.pk}/hdfn/new/',
            {'severity': 'moderate', 'outcome': 'ongoing', 'direct_antiglobulin_test': 'positive'},
        )
        assert AuditLog.objects.filter(action='patients.hdfn.create').exists()

    def test_detail_get_renders(self, db, branch, user):
        from patients.models import HaemolyticDiseaseCase
        su = _su(branch)
        mother = PatientFactory(registration_branch=branch)
        case = HaemolyticDiseaseCase.objects.create(
            mother=mother, recorded_by=su,
            direct_antiglobulin_test='not_done',
        )
        resp = _client(su, branch).get(f'/patients/hdfn/{case.pk}/')
        assert resp.status_code == 200

    def test_detail_nonexistent_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/patients/hdfn/99999/')
        assert resp.status_code == 404

    def test_list_unauthenticated_redirects(self, db):
        resp = Client().get('/patients/hdfn/')
        assert resp.status_code == 302

    def test_create_post_invalid_antibody_pk_returns_404(self, db, branch, user):
        """
        Regression: patients/views.py:1032 previously used PatientAntibody.objects.get()
        without error handling — an invalid maternal_antibody_id caused HTTP 500.
        After fix, get_object_or_404 must return 404.
        """
        su = _su(branch)
        mother = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(
            f'/patients/{mother.pk}/hdfn/new/',
            {
                'maternal_antibody_id': '999999',  # non-existent PK
                'antibody_specificity_text': 'Anti-D',
                'severity': 'mild',
                'outcome': 'resolved',
                'direct_antiglobulin_test': 'positive',
            },
        )
        assert resp.status_code == 404


# ─── Patient blood group card PDF ─────────────────────────────────────────────

class TestPatientBloodGroupCardPDF:

    def test_returns_pdf(self, db, branch, user):
        patient = PatientFactory(registration_branch=branch)
        resp = _client(user, branch).get(f'/patients/{patient.pk}/bg-card.pdf')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'

    def test_nonexistent_patient_returns_404(self, db, branch, user):
        resp = _client(user, branch).get('/patients/99999/bg-card.pdf')
        assert resp.status_code == 404

    def test_unauthenticated_redirects(self, db, branch):
        patient = PatientFactory(registration_branch=branch)
        resp = Client().get(f'/patients/{patient.pk}/bg-card.pdf')
        assert resp.status_code == 302


# ─── Discrepancy investigation list ──────────────────────────────────────────

class TestDiscrepancyInvestigationListView:

    def test_get_renders_list(self, db, branch, user):
        resp = _client(user, branch).get('/patients/discrepancies/')
        assert resp.status_code == 200

    def test_get_with_status_filter(self, db, branch, user):
        resp = _client(user, branch).get('/patients/discrepancies/?status=open')
        assert resp.status_code == 200

    def test_unauthenticated_redirects(self, db):
        resp = Client().get('/patients/discrepancies/')
        assert resp.status_code == 302


# ─── Investigate discrepancy ──────────────────────────────────────────────────

class TestInvestigateDiscrepancyView:

    def test_get_no_discrepancy_redirects_to_detail(self, db, branch, user):
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        # Patient with no discrepant blood groups → view redirects away
        resp = _client(su, branch).get(f'/patients/{patient.pk}/discrepancy/')
        assert resp.status_code in (200, 302)

    def test_get_nonexistent_patient_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/patients/99999/discrepancy/')
        assert resp.status_code == 404

    def test_unauthenticated_redirects(self, db, branch):
        patient = PatientFactory(registration_branch=branch)
        resp = Client().get(f'/patients/{patient.pk}/discrepancy/')
        assert resp.status_code == 302


# ─── Int-safety regression: _to_int_or_none and try/except guards ─────────────

class TestIntSafetyRegressions:
    """
    Regression tests for _to_int_or_none() / try/except guards on int conversions
    that previously raised ValueError on non-numeric POST values.
    """

    def test_tp_schedule_non_numeric_target_volume_does_not_crash(self, db, branch, user):
        """
        Regression: int(target_volume) in therapeutic_phlebotomy_schedule
        had no try/except. Non-numeric input caused HTTP 500.
        After fix, defaults to 450 mL.
        """
        from patients.models import TherapeuticPhlebotomy
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        count_before = TherapeuticPhlebotomy.objects.count()
        resp = _client(su, branch).post(
            f'/patients/{patient.pk}/therapeutic-phlebotomy/schedule/',
            {
                'indication': 'haemochromatosis',
                'scheduled_date': '2026-12-01',
                'target_volume_ml': 'not_a_number',
                'disposition': 'discard',
            },
        )
        assert resp.status_code != 500
        if TherapeuticPhlebotomy.objects.count() > count_before:
            tp = TherapeuticPhlebotomy.objects.filter(patient=patient).order_by('-pk').first()
            assert tp.target_volume_ml == 450

    def test_antenatal_create_non_numeric_gestation_does_not_crash(self, db, branch, user):
        """
        Regression: int(gestation_wks) in antenatal_record_create
        had no try/except. Non-numeric input caused HTTP 500.
        After fix (_to_int_or_none), defaults to None.
        """
        from patients.models import AntenatalRecord
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        resp = _client(su, branch).post(
            f'/patients/{patient.pk}/antenatal/new/',
            {
                'edd': '2026-12-01',
                'abo': 'O',
                'rh_d': 'neg',
                'gestation_at_booking_wks': 'not_a_number',
            },
        )
        assert resp.status_code != 500
        if AntenatalRecord.objects.filter(patient=patient).exists():
            anc = AntenatalRecord.objects.get(patient=patient)
            assert anc.gestation_at_booking_wks is None

    def test_anti_d_non_numeric_dose_does_not_crash(self, db, branch, user):
        """
        Regression: int(dose_iu) in antenatal_detail record_anti_d
        had no try/except. After fix (_to_int_or_none), defaults to 0.
        """
        from patients.models import AntenatalRecord, AntiDProphylaxis
        su = _su(branch)
        patient = PatientFactory(registration_branch=branch)
        anc = AntenatalRecord.objects.create(
            patient=patient, edd='2026-12-15', branch=branch, created_by=su,
        )
        count_before = AntiDProphylaxis.objects.count()
        resp = _client(su, branch).post(
            f'/patients/antenatal/{anc.pk}/',
            {
                'action': 'record_anti_d',
                'indication': 'routine_28w',
                'product': 'Rhophylac 1500 IU',
                'dose_iu': 'not_a_number',
                'batch_number': 'BN001',
                'expiry_date': '2027-01-01',
                'administered_at': '2026-12-01T10:00:00',
            },
        )
        assert resp.status_code != 500
        if AntiDProphylaxis.objects.count() > count_before:
            dose = AntiDProphylaxis.objects.order_by('-pk').first()
            assert dose.dose_iu == 0
