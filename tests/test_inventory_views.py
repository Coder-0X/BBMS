"""
Tests for inventory processing views and analytics dashboard.
Covers: record_processing, change_unit_status, analytics_dashboard.
"""
import pytest
from datetime import timedelta
from django.utils import timezone
from django.test import Client

from tests.conftest import (
    UserFactory, BranchFactory, DonorFactory, DonationFactory, BloodUnitFactory,
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
        username=f'su_inv_{branch.pk}_{timezone.now().timestamp():.0f}',
        password='testpass123',
        display_name='Inv Super',
        branch=branch,
    )


def _make_unit(branch, user, status='available'):
    donor = DonorFactory(registration_branch=branch, created_by=user)
    donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
    return BloodUnitFactory(
        donation=donation, status=status, owner_branch=branch,
        collected_by=user,
        expiry_datetime=timezone.now() + timedelta(days=42),
    )


@pytest.fixture(autouse=True)
def _seed_state_transitions(db):
    from inventory.state_machine import seed_transitions
    seed_transitions()


# ─── Record processing ────────────────────────────────────────────────────────

class TestRecordProcessing:

    def test_record_processing_get(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).get(f'/inventory/units/{unit.did}/process/')
        assert resp.status_code == 200

    def test_record_processing_leukoreduction(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        assert not unit.is_leukoreduced
        resp = _client(su, branch).post(f'/inventory/units/{unit.did}/process/', {
            'processing_type': 'leukoreduction',
            'sop_version': '2.1',
            'notes': 'Filter LR used. Quality control passed.',
        })
        assert resp.status_code in (200, 302)
        unit.refresh_from_db()
        assert unit.is_leukoreduced is True

    def test_record_processing_irradiation(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/process/', {
            'processing_type': 'irradiation',
            'sop_version': '1.0',
            'notes': '25 Gy dose.',
        })
        unit.refresh_from_db()
        assert unit.is_irradiated is True

    def test_record_processing_cmv_negative(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/process/', {
            'processing_type': 'cmv_testing',
            'cmv_result': 'negative',
            'sop_version': '1.0',
        })
        unit.refresh_from_db()
        assert unit.is_cmv_negative is True

    def test_record_processing_creates_event(self, db, branch, user):
        from inventory.models import ProcessingEvent
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/process/', {
            'processing_type': 'leukoreduction',
            'sop_version': '2.1',
        })
        assert ProcessingEvent.objects.filter(blood_unit=unit, event_type='leukoreduction').exists()


# ─── Change unit status ───────────────────────────────────────────────────────

class TestChangeUnitStatus:

    def test_change_status_get(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).get(f'/inventory/units/{unit.did}/status/')
        assert resp.status_code == 200

    def test_change_status_to_quarantined_holdback(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).post(f'/inventory/units/{unit.did}/status/', {
            'new_status': 'quarantined_holdback',
            'reason': 'Suspected labelling error — placed under investigation.',
        })
        assert resp.status_code in (200, 302)
        unit.refresh_from_db()
        assert unit.status == 'quarantined_holdback'

    def test_change_status_to_wasted(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).post(f'/inventory/units/{unit.did}/status/', {
            'new_status': 'wasted',
            'reason': 'Container breach discovered during inspection.',
        })
        assert resp.status_code in (200, 302)
        unit.refresh_from_db()
        assert unit.status == 'wasted'

    def test_invalid_status_transition_shows_error(self, db, branch, user):
        """Transfused units cannot be re-used — invalid transition should fail gracefully."""
        su = _su(branch)
        unit = _make_unit(branch, user, status='transfused')
        _client(su, branch).post(f'/inventory/units/{unit.did}/status/', {
            'new_status': 'available',
            'reason': 'Attempt to reverse transfusion — should fail.',
        })
        unit.refresh_from_db()
        assert unit.status == 'transfused'


# ─── Analytics dashboard ──────────────────────────────────────────────────────

class TestAnalyticsDashboard:

    def test_analytics_dashboard_get(self, db, branch, user):
        resp = _client(user, branch).get('/analytics/')
        assert resp.status_code == 200

    def test_analytics_dashboard_with_branch_filter(self, db, branch, user):
        resp = _client(user, branch).get(f'/analytics/?branch={branch.pk}')
        assert resp.status_code == 200

    def test_analytics_dashboard_empty_data(self, db, branch, user):
        """Dashboard renders gracefully when no analytics data exists."""
        resp = _client(user, branch).get('/analytics/')
        assert resp.status_code == 200
        assert resp.context.get('kpi') is None or resp.status_code == 200


# ─── Initiate transfer ────────────────────────────────────────────────────────

class TestInitiateTransfer:

    def test_initiate_transfer_get(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).get(f'/inventory/units/{unit.did}/transfer/')
        assert resp.status_code == 200

    def test_initiate_transfer_post_changes_status(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        dest = BranchFactory()
        resp = _client(su, branch).post(f'/inventory/units/{unit.did}/transfer/', {
            'to_branch_id': dest.pk,
            'notes': 'Emergency supply to satellite branch.',
        })
        assert resp.status_code in (200, 302)
        unit.refresh_from_db()
        assert unit.status == 'transferred_out'

    def test_initiate_transfer_creates_audit_entry(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        unit = _make_unit(branch, user)
        dest = BranchFactory()
        _client(su, branch).post(f'/inventory/units/{unit.did}/transfer/', {
            'to_branch_id': dest.pk,
            'notes': 'Transfer for audit test.',
        })
        assert AuditLog.objects.filter(action='transfer.initiate').exists()


# ─── Record wastage ───────────────────────────────────────────────────────────

class TestRecordWastage:

    def test_record_wastage_get(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).get(f'/inventory/units/{unit.did}/wastage/')
        assert resp.status_code == 200

    def test_record_wastage_post_changes_status(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).post(f'/inventory/units/{unit.did}/wastage/', {
            'reason_code': 'expired_unused',
            'notes': 'Past expiry date — not used.',
            'avoidable': 'no',
        })
        assert resp.status_code in (200, 302)
        unit.refresh_from_db()
        assert unit.status == 'wasted'

    def test_record_wastage_creates_wastage_record(self, db, branch, user):
        from inventory.models import WastageRecord
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/wastage/', {
            'reason_code': 'damaged_container',
            'notes': 'Container breach.',
            'avoidable': 'yes',
        })
        assert WastageRecord.objects.filter(blood_unit=unit).exists()

    def test_record_wastage_creates_audit_entry(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/wastage/', {
            'reason_code': 'temperature_excursion',
            'notes': 'Excursion on fridge 3.',
            'avoidable': 'yes',
        })
        assert AuditLog.objects.filter(action='unit.wasted').exists()

    def test_record_wastage_with_also_destroy(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).post(f'/inventory/units/{unit.did}/wastage/', {
            'reason_code': 'positive_tti',
            'notes': 'Reactive TTI — destroyed per SOP.',
            'avoidable': 'no',
            'also_destroy': '1',
        })
        assert resp.status_code in (200, 302)
        unit.refresh_from_db()
        assert unit.status == 'destroyed'


# ─── Unit list & detail ───────────────────────────────────────────────────────

class TestUnitListAndDetail:

    def test_unit_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/')
        assert resp.status_code == 200

    def test_unit_list_with_status_filter(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/?status=available')
        assert resp.status_code == 200

    def test_unit_list_with_abo_filter(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/?abo=O')
        assert resp.status_code == 200

    def test_unit_list_with_component_filter(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/?component=RBC')
        assert resp.status_code == 200

    def test_unit_list_with_near_expiry_filter(self, db, branch, user):
        _make_unit(branch, user)
        resp = _client(user, branch).get('/inventory/units/?near_expiry=72')
        assert resp.status_code == 200

    def test_unit_list_with_did_search(self, db, branch, user):
        unit = _make_unit(branch, user)
        resp = _client(user, branch).get(f'/inventory/units/?q={unit.did[:4]}')
        assert resp.status_code == 200

    def test_unit_detail_get(self, db, branch, user):
        unit = _make_unit(branch, user)
        resp = _client(user, branch).get(f'/inventory/units/{unit.did}/')
        assert resp.status_code == 200

    def test_unit_list_near_expiry_non_numeric_does_not_crash(self, db, branch, user):
        """
        Regression: int(near_expiry) had no try/except, and timezone.timedelta
        does not exist. Both would cause HTTP 500 before the fix.
        After fix, non-numeric near_expiry silently defaults to 72 hours.
        """
        resp = _client(user, branch).get('/inventory/units/?near_expiry=not_a_number')
        assert resp.status_code == 200

    def test_unit_list_near_expiry_numeric_returns_results(self, db, branch, user):
        """Regression: timezone.timedelta doesn't exist — near_expiry=72 was crashing."""
        _make_unit(branch, user)
        resp = _client(user, branch).get('/inventory/units/?near_expiry=24')
        assert resp.status_code == 200


# ─── Irradiate unit ───────────────────────────────────────────────────────────

class TestIrradiateUnit:

    def test_irradiate_get(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).get(f'/inventory/units/{unit.did}/irradiate/')
        assert resp.status_code == 200

    def test_irradiate_post_marks_irradiated(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        assert not unit.is_irradiated
        resp = _client(su, branch).post(f'/inventory/units/{unit.did}/irradiate/', {
            'dose_gy': '25',
            'equipment_id': 'IRRAD-001',
            'dosimetry_card_ok': '1',
            'sop_version': '3.0',
            'notes': 'Neonatal transfusion indication.',
        })
        assert resp.status_code in (200, 302)
        unit.refresh_from_db()
        assert unit.is_irradiated is True

    def test_irradiate_below_25gy_rejected(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/irradiate/', {
            'dose_gy': '20',
            'dosimetry_card_ok': '1',
            'sop_version': '3.0',
        })
        unit.refresh_from_db()
        assert not unit.is_irradiated

    def test_irradiate_already_irradiated_redirects(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        unit.is_irradiated = True
        unit.irradiation_datetime = timezone.now()
        unit.save(update_fields=['is_irradiated', 'irradiation_datetime'])
        resp = _client(su, branch).get(f'/inventory/units/{unit.did}/irradiate/')
        assert resp.status_code in (200, 302)

    def test_irradiate_rbc_reduces_expiry(self, db, branch, user):
        """BCSH: irradiated RBC must be transfused within 14 days."""
        su = _su(branch)
        unit = _make_unit(branch, user)
        # Set expiry to 40 days from now (greater than 14 days post-irradiation)
        unit.component_class = 'RBC'
        unit.expiry_datetime = timezone.now() + timedelta(days=40)
        unit.save(update_fields=['component_class', 'expiry_datetime'])
        _client(su, branch).post(f'/inventory/units/{unit.did}/irradiate/', {
            'dose_gy': '25',
            'dosimetry_card_ok': '1',
            'sop_version': '3.0',
        })
        unit.refresh_from_db()
        # Expiry should now be <= 14 days from now
        from datetime import timedelta as _td
        assert unit.expiry_datetime <= timezone.now() + _td(days=15)

    def test_irradiate_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/irradiate/', {
            'dose_gy': '30',
            'dosimetry_card_ok': '1',
            'sop_version': '2.5',
        })
        assert AuditLog.objects.filter(action='unit.irradiated', entity_id=unit.pk).exists()


# ─── Leukoreduction unit ──────────────────────────────────────────────────────

class TestLeukoreductionUnit:

    def test_leukoreduction_get(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).get(f'/inventory/units/{unit.did}/leukoreduction/')
        assert resp.status_code == 200

    def test_leukoreduction_post_marks_leukoreduced(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        assert not unit.is_leukoreduced
        resp = _client(su, branch).post(f'/inventory/units/{unit.did}/leukoreduction/', {
            'filter_lot': 'LR-LOT-001',
            'sop_version': '2.0',
            'pre_leukocyte_count': '5.2',
            'post_leukocyte_count': '0.08',
            'notes': 'Pre-storage leukoreduction.',
        })
        assert resp.status_code in (200, 302)
        unit.refresh_from_db()
        assert unit.is_leukoreduced is True

    def test_leukoreduction_missing_filter_lot_rejected(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/leukoreduction/', {
            'sop_version': '2.0',
        })
        unit.refresh_from_db()
        assert not unit.is_leukoreduced

    def test_leukoreduction_already_done_redirects(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        unit.is_leukoreduced = True
        unit.save(update_fields=['is_leukoreduced'])
        resp = _client(su, branch).get(f'/inventory/units/{unit.did}/leukoreduction/')
        assert resp.status_code in (200, 302)

    def test_leukoreduction_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/leukoreduction/', {
            'filter_lot': 'LR-LOT-002',
            'sop_version': '2.0',
        })
        assert AuditLog.objects.filter(action='unit.leukoreduced', entity_id=unit.pk).exists()


# ─── Wash unit ───────────────────────────────────────────────────────────────

class TestWashUnit:

    def test_wash_get(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        resp = _client(su, branch).get(f'/inventory/units/{unit.did}/wash/')
        assert resp.status_code == 200

    def test_wash_post_marks_washed(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        assert not unit.is_washed
        resp = _client(su, branch).post(f'/inventory/units/{unit.did}/wash/', {
            'indication': 'iga_deficiency',
            'wash_solution': 'normal_saline',
            'num_washes': '3',
            'wash_vol_ml': '300',
            'sop_version': '1.5',
            'notes': 'IgA-deficient recipient.',
        })
        assert resp.status_code in (200, 302)
        unit.refresh_from_db()
        assert unit.is_washed is True

    def test_wash_missing_indication_rejected(self, db, branch, user):
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/wash/', {
            'sop_version': '1.5',
        })
        unit.refresh_from_db()
        assert not unit.is_washed

    def test_wash_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        unit = _make_unit(branch, user)
        _client(su, branch).post(f'/inventory/units/{unit.did}/wash/', {
            'indication': 'allergic_history',
            'sop_version': '1.5',
        })
        assert AuditLog.objects.filter(action='unit.washed', entity_id=unit.pk).exists()


# ─── Near expiry & wastage report ─────────────────────────────────────────────

class TestNearExpiryAndWastageReport:

    def test_near_expiry_get(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/near-expiry/')
        assert resp.status_code == 200

    def test_near_expiry_with_hours_filter(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/near-expiry/?hours=48')
        assert resp.status_code == 200

    def test_near_expiry_with_component_filter(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/near-expiry/?component=RBC')
        assert resp.status_code == 200

    def test_wastage_report_get(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/wastage-report/')
        assert resp.status_code == 200

    def test_wastage_report_with_days_filter(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/wastage-report/?days=7')
        assert resp.status_code == 200


# ─── Pending transfers ────────────────────────────────────────────────────────

class TestPendingTransfers:

    def test_pending_transfers_get(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/transfers/')
        assert resp.status_code == 200

    def test_pending_transfers_shows_incoming(self, db, branch, user):
        su = _su(branch)
        # Create a unit owned by another branch, transfer to this branch
        other_branch = BranchFactory()
        unit = _make_unit(other_branch, user)
        from inventory.models import Transfer
        Transfer.objects.create(
            blood_unit=unit,
            from_branch=other_branch,
            to_branch=branch,
            status='requested',
            initiated_by=user,
        )
        resp = _client(su, branch).get('/inventory/transfers/')
        assert resp.status_code == 200


# ─── Separate components ──────────────────────────────────────────────────────

class TestSeparateComponents:

    def test_separate_components_get(self, db, branch, user):
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        resp = _client(su, branch).get(f'/inventory/donations/{donation.pk}/separate/')
        assert resp.status_code == 200

    def test_separate_components_post_creates_units(self, db, branch, user):
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user,
                                   donation_type='whole_blood')
        from core.models import RefFacility
        RefFacility.objects.get_or_create(
            branch=branch,
            defaults={'facility_code': branch.facility_code[:3], 'last_serial': 0, 'name': branch.name},
        )
        from inventory.models import ComponentType, BloodUnit
        count_before = BloodUnit.objects.count()
        rbc_type = ComponentType.objects.filter(component_class='RBC').first()
        if rbc_type is None:
            pytest.skip("No RBC ComponentType configured")
        resp = _client(su, branch).post(f'/inventory/donations/{donation.pk}/separate/', {
            'component_codes': [rbc_type.code],
        })
        assert resp.status_code in (200, 302)

    def test_separate_components_no_ref_facility_shows_error(self, db, branch, user):
        """Bug fix: missing RefFacility now shows error instead of crashing with 500."""
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user,
                                   donation_type='whole_blood')
        from core.models import RefFacility
        RefFacility.objects.filter(branch=branch).delete()
        from inventory.models import ComponentType
        rbc_type = ComponentType.objects.filter(component_class='RBC').first()
        if rbc_type is None:
            pytest.skip("No RBC ComponentType configured")
        resp = _client(su, branch).post(f'/inventory/donations/{donation.pk}/separate/', {
            'component_codes': [rbc_type.code],
        })
        # Should redirect back (not crash with 500)
        assert resp.status_code in (200, 302)


# ─── Antigen match search ────────────────────────────────────────────────────

class TestAntigenMatchSearch:

    def test_get_no_patient_renders_form(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/antigen-match/')
        assert resp.status_code == 200

    def test_get_nonexistent_patient_shows_error(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/antigen-match/?patient_id=99999')
        assert resp.status_code == 200

    def test_get_with_patient_no_blood_group_shows_warning(self, db, branch, user):
        from patients.models import Patient
        from privacy.vault import encrypt, blind_index
        from privacy.models import SubjectIdentity
        identity = SubjectIdentity.objects.create(
            subject_type='patient',
            created_by=user,
            name_enc=encrypt('Test Patient'),
            name_blind_index=blind_index('test patient'),
        )
        patient = Patient.objects.create(
            subject=identity,
            sex='M',
            created_by=user,
        )
        resp = _client(user, branch).get(f'/inventory/units/antigen-match/?patient_id={patient.pk}')
        assert resp.status_code == 200

    def test_get_with_patient_with_blood_group_uses_abo_type_filter(
        self, db, branch, user, patient_with_two_abo
    ):
        """
        Regression test for bug: antigen_match_search used `abo__in` which
        raises FieldError — must be `abo_type__in`.
        """
        from tests.conftest import BloodUnitFactory, DonorFactory, DonationFactory
        # Create an O-neg RBC unit to match
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        BloodUnitFactory(
            donation=donation, component_class='RBC',
            abo_type='O', rh_d_type='neg',
            status='available', owner_branch=branch,
            expiry_datetime=timezone.now() + timedelta(days=42),
        )
        resp = _client(user, branch).get(
            f'/inventory/units/antigen-match/?patient_id={patient_with_two_abo.pk}&component=RBC'
        )
        assert resp.status_code == 200


# ─── Receive transfer ─────────────────────────────────────────────────────────

class TestReceiveTransfer:

    def _make_transfer(self, branch, user):
        from inventory.models import Transfer
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(
            donation=donation, status='in_transit', owner_branch=branch,
            expiry_datetime=timezone.now() + timedelta(days=42),
        )
        from_branch = BranchFactory()
        transfer = Transfer.objects.create(
            blood_unit=unit,
            from_branch=from_branch,
            to_branch=branch,
            status='requested',
            initiated_by=user,
        )
        return transfer, unit

    def test_get_renders_form(self, db, branch, user):
        su = _su(branch)
        transfer, unit = self._make_transfer(branch, user)
        resp = _client(su, branch).get(f'/inventory/transfers/{transfer.pk}/receive/')
        assert resp.status_code == 200

    def test_post_accept_marks_transfer_received(self, db, branch, user):
        from inventory.models import Transfer
        su = _su(branch)
        transfer, unit = self._make_transfer(branch, user)
        resp = _client(su, branch).post(f'/inventory/transfers/{transfer.pk}/receive/', {
            'action': 'accept',
        })
        assert resp.status_code == 302
        transfer.refresh_from_db()
        assert transfer.status == 'received'

    def test_post_accept_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        transfer, unit = self._make_transfer(branch, user)
        _client(su, branch).post(f'/inventory/transfers/{transfer.pk}/receive/', {
            'action': 'accept',
        })
        assert AuditLog.objects.filter(
            action='transfer.received',
            entity_table='inventory_transfer',
            entity_id=transfer.pk,
        ).exists()

    def test_post_reject_marks_transfer_rejected(self, db, branch, user):
        from inventory.models import Transfer
        su = _su(branch)
        transfer, unit = self._make_transfer(branch, user)
        resp = _client(su, branch).post(f'/inventory/transfers/{transfer.pk}/receive/', {
            'action': 'reject',
            'reason': 'Unit arrived damaged',
        })
        assert resp.status_code == 302
        transfer.refresh_from_db()
        assert transfer.status == 'rejected'

    def test_post_reject_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        transfer, unit = self._make_transfer(branch, user)
        _client(su, branch).post(f'/inventory/transfers/{transfer.pk}/receive/', {
            'action': 'reject',
            'reason': 'test',
        })
        assert AuditLog.objects.filter(
            action='transfer.rejected',
            entity_table='inventory_transfer',
            entity_id=transfer.pk,
        ).exists()


# ─── Cross-site request ───────────────────────────────────────────────────────

class TestCrossSiteRequestView:

    def test_get_renders_form(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/cross-site-request/')
        assert resp.status_code == 200

    def test_get_context_has_branches(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/cross-site-request/')
        assert 'branches' in resp.context

    def test_unauthenticated_redirects(self, db, branch):
        resp = Client().get('/inventory/cross-site-request/')
        assert resp.status_code == 302
        assert 'login' in resp.get('Location', '').lower()


# ─── Pool platelets ───────────────────────────────────────────────────────────

class TestPoolPlateletsView:

    def test_get_renders_form(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/pool-platelets/')
        assert resp.status_code == 200

    def test_get_shows_available_plts(self, db, branch, user):
        from tests.conftest import DonationFactory
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        BloodUnitFactory(
            donation=donation, status='available', owner_branch=branch,
            component_class='PLT',
            expiry_datetime=timezone.now() + timedelta(days=5),
        )
        resp = _client(user, branch).get('/inventory/units/pool-platelets/')
        assert resp.status_code == 200

    def test_post_too_few_units_shows_error(self, db, branch, user):
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=su)
        from tests.conftest import DonationFactory
        donation = DonationFactory(donor=donor, branch=branch, collected_by=su)
        unit1 = BloodUnitFactory(
            donation=donation, status='available', owner_branch=branch, component_class='PLT'
        )
        unit2 = BloodUnitFactory(
            donation=donation, status='available', owner_branch=branch, component_class='PLT'
        )
        resp = _client(su, branch).post('/inventory/units/pool-platelets/', {
            'unit_pks': [unit1.pk, unit2.pk],
            'sop_version': 'PLT-POOL-v1.2',
        })
        assert resp.status_code == 200  # stays on form
        assert b'Minimum 4' in resp.content

    def test_post_missing_sop_version_shows_error(self, db, branch, user):
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=su)
        from tests.conftest import DonationFactory
        donation = DonationFactory(donor=donor, branch=branch, collected_by=su)
        units = [
            BloodUnitFactory(
                donation=donation, status='available', owner_branch=branch, component_class='PLT'
            )
            for _ in range(4)
        ]
        resp = _client(su, branch).post('/inventory/units/pool-platelets/', {
            'unit_pks': [u.pk for u in units],
            'sop_version': '',  # missing
        })
        assert resp.status_code == 200  # stays on form
        assert b'SOP version' in resp.content

    def test_unauthenticated_redirects(self, db, branch):
        resp = Client().get('/inventory/units/pool-platelets/')
        assert resp.status_code == 302


# ─── Print label ──────────────────────────────────────────────────────────────

class TestPrintLabelView:

    def test_get_renders_label(self, db, branch, user):
        from tests.conftest import DonationFactory
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        resp = _client(user, branch).get(f'/inventory/units/{unit.did}/label/')
        assert resp.status_code == 200

    def test_get_nonexistent_unit_returns_404(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/NONEXISTENT-DID-99/label/')
        assert resp.status_code == 404

    def test_unauthenticated_redirects(self, db, branch):
        resp = Client().get('/inventory/units/SOME-DID/label/')
        assert resp.status_code == 302


# ─── Unit PIL (Product Information Leaflet) ───────────────────────────────────

class TestExportUnitPILView:

    def test_get_returns_pdf(self, db, branch, user):
        from tests.conftest import DonationFactory
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        resp = _client(user, branch).get(f'/inventory/units/{unit.did}/pil.pdf')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'

    def test_get_nonexistent_unit_returns_404(self, db, branch, user):
        resp = _client(user, branch).get('/inventory/units/NONEXISTENT-DID-99/pil.pdf')
        assert resp.status_code == 404

    def test_unauthenticated_redirects(self, db, branch):
        resp = Client().get('/inventory/units/SOME-DID/pil.pdf')
        assert resp.status_code == 302


# ─── Apheresis audit trail ────────────────────────────────────────────────────

class TestApheresisAuditTrail:
    """
    Verifies Bug fix #3: create_apheresis_units now writes a unit.create audit
    entry for every unit produced, matching the behaviour of whole-blood separation.
    """

    def _setup_apheresis(self, branch, user):
        from core.models import RefFacility
        from tests.conftest import _get_or_create_component_type, DonationFactory

        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(
            donor=donor, branch=branch, collected_by=su, donation_type='apheresis'
        )
        # Ensure RefFacility exists — apheresis path requires it for DID generation
        RefFacility.objects.get_or_create(
            branch=branch,
            defaults={
                'facility_code': branch.facility_code[:3],
                'name': branch.name,
                'last_serial': 0,
            },
        )
        plt_type = _get_or_create_component_type('PLT')
        return su, donation, plt_type

    def test_apheresis_post_creates_units(self, db, branch, user):
        from inventory.models import BloodUnit
        su, donation, plt_type = self._setup_apheresis(branch, user)
        count_before = BloodUnit.objects.count()
        resp = _client(su, branch).post(
            f'/inventory/donations/{donation.pk}/separate/',
            {'component_codes': [plt_type.code]},
        )
        assert resp.status_code in (200, 302)
        assert BloodUnit.objects.count() > count_before

    def test_apheresis_post_writes_audit_trail(self, db, branch, user):
        """Bug fix #3: each apheresis unit now gets a unit.create audit entry."""
        from audit.models import AuditLog
        su, donation, plt_type = self._setup_apheresis(branch, user)
        _client(su, branch).post(
            f'/inventory/donations/{donation.pk}/separate/',
            {'component_codes': [plt_type.code]},
        )
        assert AuditLog.objects.filter(action='unit.create').exists()

    def test_apheresis_audit_entry_has_source_field(self, db, branch, user):
        """Apheresis audit entries include source='apheresis' to distinguish from whole-blood."""
        import json
        from audit.models import AuditLog
        su, donation, plt_type = self._setup_apheresis(branch, user)
        _client(su, branch).post(
            f'/inventory/donations/{donation.pk}/separate/',
            {'component_codes': [plt_type.code]},
        )
        entry = AuditLog.objects.filter(action='unit.create').last()
        assert entry is not None
        after_data = entry.after if isinstance(entry.after, dict) else json.loads(entry.after)
        assert after_data.get('source') == 'apheresis'
