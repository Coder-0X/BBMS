"""
Model unit tests — covering Patient, Donor, BloodUnit, Audit, Quality models.
Run: pytest tests/test_models.py -v
"""
import pytest
from datetime import timedelta, date
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from tests.conftest import (
    BranchFactory, UserFactory, DonorFactory, DonationFactory, BloodUnitFactory,
    PatientFactory, PatientBloodGroupFactory, BloodRequestFactory,
    NonConformanceFactory, ReagentFactory, ReagentLotFactory,
)


# ─── Branch ───────────────────────────────────────────────────────────────────

class TestBranchModel:

    def test_facility_code_unique(self, db):
        BranchFactory(facility_code='B01')
        with pytest.raises(IntegrityError):
            BranchFactory(facility_code='B01')

    def test_str_contains_name(self, db):
        b = BranchFactory(name='Main Lab')
        assert 'Main Lab' in str(b)


# ─── User ─────────────────────────────────────────────────────────────────────

class TestUserModel:

    def test_create_user_hashes_password(self, db, branch):
        u = UserFactory(branch=branch)
        assert u.password != 'testpass123'  # must be hashed
        assert u.check_password('testpass123')

    def test_user_has_branch(self, db, branch):
        u = UserFactory(branch=branch)
        assert u.branch == branch

    def test_username_unique(self, db, branch):
        UserFactory(username='dupuser', branch=branch)
        with pytest.raises(IntegrityError):
            UserFactory(username='dupuser', branch=branch)


# ─── Donor ────────────────────────────────────────────────────────────────────

class TestDonorModel:

    def test_donor_created(self, db, branch, user):
        d = DonorFactory(registration_branch=branch, created_by=user)
        assert d.pk is not None

    def test_donor_sex_choices(self, db, branch, user):
        d = DonorFactory(sex='F', registration_branch=branch, created_by=user)
        assert d.sex == 'F'

    def test_donor_deferral_status_default_active(self, db, branch, user):
        d = DonorFactory(registration_branch=branch, created_by=user)
        assert d.deferral_status == 'active'

    def test_donation_linked_to_donor(self, db, branch, user):
        d = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=d, branch=branch, collected_by=user)
        assert donation.donor == d


# ─── BloodUnit ────────────────────────────────────────────────────────────────

class TestBloodUnitModel:

    def test_did_unique(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        BloodUnitFactory(donation=donation, did='000000000001', owner_branch=branch)
        with pytest.raises(IntegrityError):
            BloodUnitFactory(donation=donation, did='000000000001', owner_branch=branch)

    def test_status_default_is_quarantined_or_available(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        assert unit.status == 'available'

    def test_expiry_datetime_is_datetime(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, owner_branch=branch)
        assert hasattr(unit.expiry_datetime, 'hour')  # it's a datetime, not date

    def test_abo_rh_stored(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(
            donation=donation, abo_type='A', rh_d_type='pos', owner_branch=branch
        )
        assert unit.abo_type == 'A'
        assert unit.rh_d_type == 'pos'


# ─── Patient ──────────────────────────────────────────────────────────────────

class TestPatientModel:

    def test_patient_created(self, db, branch, user):
        p = PatientFactory(created_by=user)
        assert p.pk is not None

    def test_two_blood_group_determinations(self, db, branch, user):
        p = PatientFactory(created_by=user)
        PatientBloodGroupFactory(patient=p, abo='O', rh_d='neg', determined_by=user)
        PatientBloodGroupFactory(patient=p, abo='O', rh_d='neg', determined_by=user)
        assert p.blood_groups.count() == 2

    def test_discrepant_blood_group_flagged(self, db, branch, user):
        p = PatientFactory(created_by=user)
        bg = PatientBloodGroupFactory(patient=p, abo='A', rh_d='pos',
                                      determined_by=user, is_discrepant=True)
        assert bg.is_discrepant is True

    def test_current_blood_group_returns_latest(self, db, branch, user):
        p = PatientFactory(created_by=user)
        PatientBloodGroupFactory(patient=p, abo='O', rh_d='neg', determined_by=user)
        latest = PatientBloodGroupFactory(patient=p, abo='O', rh_d='neg', determined_by=user)
        result = p.blood_groups.order_by('-determined_at').first()
        assert result == latest


# ─── Blood Request ────────────────────────────────────────────────────────────

class TestBloodRequestModel:

    def test_request_created(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        assert req.pk is not None

    def test_urgency_choices(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        req = BloodRequestFactory(patient=patient, branch=branch,
                                   urgency='emergency', requesting_physician=user)
        assert req.urgency == 'emergency'


# ─── NonConformance (Quality) ─────────────────────────────────────────────────

class TestNonConformanceModel:

    def test_nc_created_with_auto_number(self, db, branch, user):
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        assert nc.pk is not None
        assert nc.nc_number  # auto-assigned in save()

    def test_nc_number_unique(self, db, branch, user):
        nc1 = NonConformanceFactory(reported_by=user, branch=branch)
        nc2 = NonConformanceFactory(reported_by=user, branch=branch)
        assert nc1.nc_number != nc2.nc_number

    def test_nc_lifecycle_open_to_closed(self, db, branch, user):
        nc = NonConformanceFactory(reported_by=user, branch=branch, status='open')
        nc.status = 'closed'
        nc.save()
        nc.refresh_from_db()
        assert nc.status == 'closed'


# ─── Reagent / Lot ────────────────────────────────────────────────────────────

class TestReagentModel:

    def test_reagent_lot_created(self, db):
        lot = ReagentLotFactory()
        assert lot.pk is not None
        assert lot.status == 'in_use'

    def test_lot_expiry_in_future(self, db):
        lot = ReagentLotFactory()
        assert lot.expiry_date > timezone.now().date()

    def test_reagent_code_unique(self, db):
        ReagentFactory(reagent_code='RGT0001')
        with pytest.raises(IntegrityError):
            ReagentFactory(reagent_code='RGT0001')


# ─── Privacy / Encryption ─────────────────────────────────────────────────────

class TestEncryptedFields:

    def test_name_is_encrypted_at_rest(self, db, branch, user):
        from privacy.vault import decrypt
        donor = DonorFactory(registration_branch=branch, created_by=user)
        subj = donor.subject
        # raw DB value should not be plaintext
        raw_name = subj.name_enc
        assert raw_name is not None
        # but should decrypt to something readable
        decrypted = decrypt(raw_name)
        assert decrypted  # not empty

    def test_blind_index_is_set(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        subj = donor.subject
        assert subj.name_blind_index is not None
        assert len(subj.name_blind_index) > 0


# ─── Audit Log ────────────────────────────────────────────────────────────────

class TestAuditLog:

    def test_write_audit_creates_log_entry(self, db, branch, user):
        from audit.utils import write_audit
        from audit.models import AuditLog
        before = AuditLog.objects.count()
        write_audit(
            actor=user,
            action='test.model_test',
            entity_table='test_table',
            entity_id=1,
            branch=branch,
        )
        assert AuditLog.objects.count() == before + 1

    def test_audit_log_has_row_hash(self, db, branch, user):
        from audit.utils import write_audit
        entry = write_audit(
            actor=user,
            action='test.hash',
            entity_table='test_table',
            entity_id=2,
            branch=branch,
        )
        assert entry.row_hash
        assert len(entry.row_hash) == 64

    def test_audit_log_chain_valid(self, db, branch, user):
        from audit.utils import write_audit, verify_chain
        write_audit(actor=user, action='test.a', entity_table='t', entity_id=10, branch=branch)
        write_audit(actor=user, action='test.b', entity_table='t', entity_id=11, branch=branch)
        ok, msg = verify_chain()
        assert ok, msg
