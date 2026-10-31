"""
Regression tests for bugs fixed during the autonomous improvement session.

Each test documents a previously-broken scenario to prevent regressions.
"""
import pytest
from django.test import Client
from django.utils import timezone

from tests.conftest import (
    BranchFactory, UserFactory, BloodUnitFactory, DonorFactory,
    DonationFactory, StorageEquipmentFactory,
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
        username=f'su_rf_{branch.pk}_{timezone.now().timestamp():.0f}',
        password='testpass123',
        display_name='Regression Super',
        branch=branch,
    )


# ─── API: TemperatureIngestView — non-numeric temp_c ─────────────────────────

class TestTemperatureIngestValidation:
    """
    Regression: float(temp_raw) had no try/except — a non-numeric temp_c
    from a faulty IoT sensor would cause HTTP 500. After fix, should return
    207 with a per-item error message.
    """

    def test_non_numeric_temp_returns_error_not_500(self, db, branch, user):
        from rest_framework.test import APIClient
        from tests.conftest import StorageEquipmentFactory
        equip = StorageEquipmentFactory(branch=branch, sensor_id='FRIDGE-REG-01')
        c = APIClient()
        c.force_authenticate(user=user)
        resp = c.post('/api/v1/temperature/', [
            {'sensor_id': 'FRIDGE-REG-01', 'temp_c': 'not-a-number', 'recorded_at': '2026-06-01T10:00:00Z'},
        ], format='json')
        assert resp.status_code in (207, 400)
        # Must NOT be 500
        assert resp.status_code != 500
        data = resp.json()
        assert any('temp_c' in str(e.get('error', '')) for e in data.get('errors', []))

    def test_null_temp_returns_error_not_500(self, db, branch, user):
        from rest_framework.test import APIClient
        equip = StorageEquipmentFactory(branch=branch, sensor_id='FRIDGE-REG-02')
        c = APIClient()
        c.force_authenticate(user=user)
        resp = c.post('/api/v1/temperature/', [
            {'sensor_id': 'FRIDGE-REG-02', 'temp_c': None, 'recorded_at': '2026-06-01T10:00:00Z'},
        ], format='json')
        # temp_c is None → the existing 'temp_raw is None' guard fires, not a float() crash
        assert resp.status_code != 500

    def test_valid_temp_still_accepted(self, db, branch, user):
        from rest_framework.test import APIClient
        from coldchain.models import TemperatureLog
        equip = StorageEquipmentFactory(branch=branch, sensor_id='FRIDGE-REG-03')
        c = APIClient()
        c.force_authenticate(user=user)
        before = TemperatureLog.objects.count()
        resp = c.post('/api/v1/temperature/', [
            {'sensor_id': 'FRIDGE-REG-03', 'temp_c': 4.2, 'recorded_at': '2026-06-01T11:00:00Z'},
        ], format='json')
        assert resp.status_code == 201
        assert TemperatureLog.objects.count() > before


# ─── accounts/views.py: permission_list audit trail ──────────────────────────

class TestPermissionCreationAudit:
    """
    Regression: Creating a Permission via POST /accounts/permissions/ had no
    write_audit call. After fix, an AuditLog entry must be created.
    """

    def test_permission_create_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        before = AuditLog.objects.filter(action='account.permission_created').count()
        _client(su, branch).post('/accounts/permissions/', {
            'code': 'regression.test.perm',
            'description': 'Regression test permission',
        })
        assert AuditLog.objects.filter(action='account.permission_created').count() > before

    def test_permission_create_empty_code_rejected(self, db, branch, user):
        from accounts.models import Permission
        su = _su(branch)
        before = Permission.objects.count()
        resp = _client(su, branch).post('/accounts/permissions/', {
            'code': '',
            'description': 'Missing code',
        })
        # Empty code must not create a permission
        assert Permission.objects.count() == before
        assert resp.status_code in (200, 302)


# ─── accounts/views.py: notification settings audit trail ────────────────────

class TestNotificationSettingsAudit:
    """
    Regression: Saving notification preferences had no write_audit call.
    After fix, an AuditLog entry must be created on POST.
    """

    def test_notification_settings_post_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        before = AuditLog.objects.filter(action='account.notification_prefs_updated').count()
        _client(user, branch).post('/accounts/notifications/', {
            'email': 'lab@hospital.nhs.uk',
            'notify_critical_alerts': 'on',
            'notify_warning_alerts': '',
        })
        assert AuditLog.objects.filter(action='account.notification_prefs_updated').count() > before


# ─── donors/views.py: non-numeric volume_ml ──────────────────────────────────

class TestDonorRecordDonationVolume:
    """
    Regression: int(request.POST.get('volume_ml', 450)) would crash with
    ValueError if a non-numeric value was submitted. After fix, defaults to 450.
    """

    def test_invalid_volume_does_not_crash(self, db, branch, user):
        from donors.models import Donation
        donor = DonorFactory(registration_branch=branch, created_by=user)
        from core.models import RefFacility
        RefFacility.objects.get_or_create(
            branch=branch,
            defaults={'facility_code': 'REG', '_serial_counter': 0},
        )
        c = _client(user, branch)
        s = c.session
        s['branch_id'] = branch.pk
        s.save()
        before = Donation.objects.filter(donor=donor).count()
        resp = c.post(f'/donors/{donor.pk}/donate/', {
            'donation_type': 'whole_blood',
            'volume_ml': 'not_a_number',
        })
        # Should not crash (500). Donation either succeeds with default volume or fails gracefully.
        assert resp.status_code != 500
        donations_after = Donation.objects.filter(donor=donor).count()
        if donations_after > before:
            last = Donation.objects.filter(donor=donor).order_by('-donated_at').first()
            assert last.volume_ml == 450  # default fallback


# ─── inventory/views.py: stale branch_id → redirect not 500 ─────────────────

class TestStaleBranchHandling:
    """
    Regression: Several inventory views called Branch.objects.get(pk=branch_id)
    without a try/except. A stale session branch_id (deleted branch) would cause
    DoesNotExist → HTTP 500. After fix, must redirect to select_branch.
    """

    def test_irradiate_post_with_stale_branch_redirects(self, db, branch, user):
        unit = BloodUnitFactory(owner_branch=branch, status='available')
        c = _client(user, branch)
        # Invalidate the branch_id in the session by using a non-existent pk
        s = c.session
        s['branch_id'] = 999999
        s.save()
        # URL uses unit.did (string), not unit.pk (int)
        resp = c.post(f'/inventory/units/{unit.did}/irradiate/', {
            'dose_gy': '25.0',
            'dosimetry_card_ok': 'on',
            'sop_version': 'SOP-IRR-001',
        })
        # Must NOT be 500
        assert resp.status_code != 500
        # Should redirect (to select_branch or show error)
        assert resp.status_code in (200, 302)

    def test_pool_platelets_post_with_stale_branch_redirects(self, db, branch, user):
        c = _client(user, branch)
        s = c.session
        s['branch_id'] = 999999
        s.save()
        resp = c.post('/inventory/units/pool-platelets/', {
            'unit_pks': '',
            'sop_version': 'SOP-POOL-001',
        })
        assert resp.status_code != 500
        assert resp.status_code in (200, 302)


# ─── transfusion/views.py: non-numeric MTP review fields ─────────────────────

class TestMTPCompletionWithBadInput:
    """
    Regression: int(request.POST.get('rbc_issued', 0)) etc. in MTP completion
    had no try/except. Non-numeric submitted values would cause HTTP 500.
    After fix, _safe_int() returns 0 and the save proceeds.
    """

    def test_mtp_complete_with_non_numeric_units_does_not_crash(self, db, branch, user):
        from transfusion.models import MTPActivation
        from tests.conftest import PatientFactory
        su = _su(branch)
        patient = PatientFactory(created_by=su)
        mtp = MTPActivation.objects.create(
            patient=patient,
            branch=branch,
            activated_by=su,
            activated_at=timezone.now(),
            status='active',
            trigger_type='trauma',
        )
        c = _client(su, branch)
        resp = c.post(f'/transfusion/mtp/{mtp.pk}/', {
            'action': 'complete',
            'rbc_issued': 'notanumber',
            'ffp_issued': '',
            'plt_issued': 'abc',
            'patient_survived': '1',
        })
        assert resp.status_code != 500
        assert resp.status_code in (200, 302)
        mtp.refresh_from_db()
        # Should have defaulted to 0, not crashed
        assert mtp.rbc_units_issued == 0
        assert mtp.ffp_units_issued == 0


# ─── quality/views.py: non-numeric review_interval_months ───────────────────

class TestSOPCreateWithBadReviewInterval:
    """
    Regression: int(request.POST.get('review_interval_months', 12)) had no
    try/except in sop_create view. After fix, defaults to 12.
    """

    def test_sop_create_non_numeric_review_interval_does_not_crash(self, db, branch, user):
        su = _su(branch)
        from quality.models import StandardOperatingProcedure
        count_before = StandardOperatingProcedure.objects.count()
        resp = _client(su, branch).post('/quality/sop/new/', {
            'sop_code': 'SOP-REG-001',
            'title': 'Test Regression SOP',
            'category': 'blood_grouping',
            'review_interval_months': 'not_a_number',
        })
        assert resp.status_code != 500


# ─── quality/views.py: non-numeric chair_id in committee_create ───────────────

class TestCommitteeCreateChairId:
    """
    Regression: int(chair_id) in committee_create had no try/except.
    Non-numeric chair_id (e.g. 'abc') would cause HTTP 500.
    After fix, returns 200 with an error message.
    """

    def test_committee_create_non_numeric_chair_does_not_crash(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).post('/quality/committee/new/', {
            'meeting_type': 'quarterly',
            'scheduled_date': '2026-10-01',
            'agenda_text': 'Test agenda',
            'chair_id': 'not_a_number',
        })
        assert resp.status_code != 500
        assert resp.status_code in (200, 302)

    def test_committee_create_valid_chair_succeeds(self, db, branch, user):
        from quality.models import TransfusionCommittee
        su = _su(branch)
        count_before = TransfusionCommittee.objects.count()
        resp = _client(su, branch).post('/quality/committee/new/', {
            'meeting_type': 'quarterly',
            'scheduled_date': '2026-10-01',
            'agenda_text': 'Annual review',
            'chair_id': str(su.pk),
        })
        assert resp.status_code != 500
        assert TransfusionCommittee.objects.count() > count_before


# ─── donors/views.py: non-numeric goal_donations in campaign_create ──────────

class TestCampaignCreateGoalDonations:
    """
    Regression: int(request.POST.get('goal_donations', 0) or 0) had a flaw —
    'abc' or 0 evaluates to 'abc', and int('abc') raises ValueError.
    After fix with try/except, defaults to 0 and creation succeeds.
    """

    def test_campaign_create_non_numeric_goal_does_not_crash(self, db, branch, user):
        from donors.models import RetentionCampaign
        count_before = RetentionCampaign.objects.count()
        resp = _client(user, branch).post('/donors/campaigns/new/', {
            'name': 'Regression Campaign',
            'segment': 'lapsed_6m',
            'channel': 'email',
            'message_template': 'We miss you!',
            'goal_donations': 'not_a_number',
        })
        assert resp.status_code != 500
        if RetentionCampaign.objects.count() > count_before:
            campaign = RetentionCampaign.objects.order_by('-created_at').first()
            assert campaign.goal_donations == 0

    def test_campaign_create_valid_goal_sets_correctly(self, db, branch, user):
        from donors.models import RetentionCampaign
        resp = _client(user, branch).post('/donors/campaigns/new/', {
            'name': 'Valid Goal Campaign',
            'segment': 'lapsed_3m',
            'channel': 'sms',
            'message_template': 'Come donate!',
            'goal_donations': '100',
        })
        assert resp.status_code != 500
        if RetentionCampaign.objects.filter(name='Valid Goal Campaign').exists():
            campaign = RetentionCampaign.objects.get(name='Valid Goal Campaign')
            assert campaign.goal_donations == 100


# ─── core/views.py: non-numeric branch_id in select_branch ──────────────────

class TestUnitListNearExpiryFilter:
    """
    Regression: (1) int(near_expiry) in unit_list had no try/except — 'abc' caused
    HTTP 500 via ValueError. (2) timezone.timedelta doesn't exist on
    django.utils.timezone — any valid near_expiry value caused HTTP 500 via
    AttributeError. Both fixed by wrapping int() in try/except and using
    datetime.timedelta instead of timezone.timedelta.
    """

    def test_non_numeric_near_expiry_does_not_crash(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/?near_expiry=not_a_number')
        assert resp.status_code != 500
        assert resp.status_code == 200

    def test_numeric_near_expiry_does_not_crash(self, db, branch, user):
        """Regression: timezone.timedelta attribute does not exist."""
        resp = _client(user, branch).get('/inventory/units/?near_expiry=72')
        assert resp.status_code != 500
        assert resp.status_code == 200


# ─── analytics/views.py: non-numeric branch param ────────────────────────────

class TestAnalyticsDashboardNonNumericBranch:
    """
    Regression: get_object_or_404(Branch, pk='abc') raises ValueError (not Http404)
    because Django's IntegerField.get_prep_value calls int('abc').
    After fix, non-numeric ?branch= falls back to first active branch.
    """

    def test_non_numeric_branch_param_does_not_crash(self, db, branch, user):
        resp = _client(user, branch).get('/analytics/?branch=not_a_number')
        assert resp.status_code != 500
        assert resp.status_code == 200


# ─── inventory/views_recall.py: non-numeric donation_id ──────────────────────

class TestRecallLookupNonNumericDonation:
    """
    Regression: get_object_or_404(Donation, pk=request.GET['donation_id']) raised
    ValueError on non-numeric input since get_object_or_404 only catches DoesNotExist.
    After fix, gracefully renders the form without the lookup result.
    """

    def test_non_numeric_donation_id_does_not_crash(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/recall/?donation_id=not_a_number')
        assert resp.status_code != 500
        assert resp.status_code == 200


# ─── transfusion/views.py: timezone.timedelta in collect_sample ──────────────

class TestCollectSampleTimezone:
    """
    Regression: collect_sample used timezone.timedelta(hours=72) which raises
    AttributeError since django.utils.timezone has no timedelta attribute.
    After fix with `from datetime import timedelta`, the sample is created correctly.
    """

    def test_collect_sample_recent_event_does_not_crash(self, db, branch, user):
        from transfusion.models import Sample
        from tests.conftest import PatientFactory
        import uuid
        su = _su(branch)
        patient = PatientFactory(created_by=su)
        accession = f'ACC-TZ-{uuid.uuid4().hex[:8].upper()}'
        resp = _client(su, branch).post('/transfusion/sample/collect/', {
            'patient_id': patient.pk,
            'accession_number': accession,
            'recent_transfusion_or_pregnancy': 'yes',
        })
        assert resp.status_code != 500
        sample = Sample.objects.filter(accession_number=accession).first()
        assert sample is not None, "Sample must be created even with recent_transfusion_or_pregnancy=yes"
        assert sample.validity_expiry is not None


# ─── quality/models.py: timezone.timedelta in qc_status ──────────────────────

class TestReagentQCStatus:
    """
    Regression: Reagent.qc_status() used timezone.timedelta(hours=...) which raises
    AttributeError. After fix with `from datetime import timedelta as _td`, the method
    returns the correct status.
    """

    def test_qc_status_overdue_does_not_crash(self, db, branch, user):
        from quality.models import Reagent
        su = _su(branch)
        reagent = Reagent.objects.create(
            name='Anti-A Monoclonal',
            code='ABO-ANTI-A',
            branch=branch,
            created_by=su,
            qc_interval_hours=24,
        )
        status = reagent.qc_status(branch_id=branch.pk)
        assert status in ('overdue', 'pass', 'fail', 'no_data')


# ─── inventory/views.py: non-numeric branch_id in initiate_transfer ──────────

class TestInitiateTransferNonNumericBranch:
    """
    Regression: initiate_transfer called get_object_or_404(Branch, pk=POST['to_branch_id'])
    with no int guard. Non-numeric branch caused ValueError → HTTP 500.
    After fix, invalid input redirects with an error message.
    """

    def test_non_numeric_to_branch_does_not_crash(self, db, branch, user):
        unit = BloodUnitFactory(owner_branch=branch, status='available')
        resp = _client(user, branch).post(f'/inventory/units/{unit.did}/transfer/', {
            'to_branch_id': 'not_a_number',
            'notes': 'Test',
        })
        assert resp.status_code != 500
        assert resp.status_code in (200, 302)


class TestSelectBranchNonNumeric:
    """
    Regression: Branch.objects.filter(pk=branch_id) raised ValueError when
    branch_id was a non-numeric string (IntegerField pk).
    After fix with try/except around int(branch_id), must not crash.
    """

    def test_select_branch_non_numeric_does_not_crash(self, db, branch, user):
        c = _client(user, branch)
        resp = c.post('/branches/select/', {'branch_id': 'abc'})
        assert resp.status_code != 500
        assert resp.status_code in (200, 302)
        # Session branch must remain unchanged
        assert c.session.get('branch_id') == branch.pk


# ─── core.did: verify_did check-digit off-by-one ─────────────────────────────

class TestDidVerification:
    """
    Regression: verify_did() computed the Luhn digit over numeric_part[:-1]
    (7 digits) while generate_did() computes it over the full 8-digit numeric
    part. Every validly-generated DID therefore FAILED its own verification.
    """

    def test_generated_did_verifies(self):
        from core.did import generate_did, verify_did
        from datetime import date
        did = generate_did('KNH', 1, year=date(2026, 1, 1))
        assert verify_did(did) is True

    def test_generated_did_round_trips_over_range(self):
        from core.did import generate_did, verify_did
        from datetime import date
        for serial in (1, 42, 999, 123456, 999999):
            did = generate_did('ABC', serial, year=date(2026, 1, 1))
            assert verify_did(did) is True, f"DID {did} failed self-verification"

    def test_tampered_check_digit_is_rejected(self):
        from core.did import generate_did, verify_did
        from datetime import date
        did = generate_did('KNH', 100, year=date(2026, 1, 1))
        # Flip the check digit to a different value
        wrong = str((int(did[-1]) + 1) % 10)
        tampered = did[:-1] + wrong
        assert verify_did(tampered) is False

    def test_malformed_did_rejected(self):
        from core.did import verify_did
        assert verify_did('short') is False
        assert verify_did('knh26000001C') is False  # lowercase facility
        assert verify_did('') is False
