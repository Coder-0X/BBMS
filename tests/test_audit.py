"""
Audit trail integrity tests.
Run: pytest tests/test_audit.py -v
"""
import pytest
from django.utils import timezone

from tests.conftest import BranchFactory, UserFactory


class TestAuditLogImmutability:

    def test_audit_log_entry_written(self, db, branch, user):
        from audit.utils import write_audit
        from audit.models import AuditLog
        before = AuditLog.objects.count()
        write_audit(
            actor=user,
            action='test.action',
            entity_table='test_table',
            entity_id=1,
            branch=branch,
        )
        assert AuditLog.objects.count() > before

    def test_audit_entry_has_row_hash(self, db, branch, user):
        from audit.utils import write_audit
        entry = write_audit(
            actor=user,
            action='test.hash_check',
            entity_table='test_table',
            entity_id=2,
            branch=branch,
        )
        assert entry.row_hash
        assert len(entry.row_hash) == 64

    def test_audit_entry_has_prev_hash(self, db, branch, user):
        from audit.utils import write_audit
        entry = write_audit(
            actor=user,
            action='test.chain_check',
            entity_table='test_table',
            entity_id=3,
            branch=branch,
        )
        assert entry.prev_hash is not None

    def test_chain_links_sequentially(self, db, branch, user):
        from audit.utils import write_audit
        e1 = write_audit(actor=user, action='test.seq1', entity_table='t', entity_id=10, branch=branch)
        e2 = write_audit(actor=user, action='test.seq2', entity_table='t', entity_id=11, branch=branch)
        assert e2.prev_hash == e1.row_hash

    def test_chain_verify_passes_on_untampered(self, db, branch, user):
        from audit.utils import write_audit, verify_chain
        write_audit(actor=user, action='test.v1', entity_table='t', entity_id=20, branch=branch)
        write_audit(actor=user, action='test.v2', entity_table='t', entity_id=21, branch=branch)
        ok, msg = verify_chain()
        assert ok, f"Chain verification failed: {msg}"

    def test_chain_detects_tampering(self, db, branch, user):
        from audit.utils import write_audit, verify_chain
        from audit.models import AuditLog
        write_audit(actor=user, action='test.t1', entity_table='t', entity_id=30, branch=branch)
        e2 = write_audit(actor=user, action='test.t2', entity_table='t', entity_id=31, branch=branch)
        # Tamper via direct DB update (bypasses any model hooks)
        AuditLog.objects.filter(pk=e2.pk).update(action='tampered.action')
        ok, _ = verify_chain()
        assert not ok

    def test_verify_chain_empty_log_returns_valid(self, db):
        """An empty audit log (no entries yet) should be considered valid."""
        from audit.models import AuditLog
        from audit.utils import verify_chain
        AuditLog.objects.all().delete()
        ok, msg = verify_chain()
        assert ok
        assert 'intact' in msg.lower()

    def test_first_entry_has_genesis_prev_hash(self, db, branch, user):
        """The first audit entry must chain from the genesis hash (64 zeros)."""
        from audit.models import AuditLog
        from audit.utils import write_audit
        AuditLog.objects.all().delete()
        entry = write_audit(actor=user, action='test.genesis', entity_table='t', entity_id=1, branch=branch)
        assert entry.prev_hash == '0' * 64
        assert entry.seq == 1


class TestElectronicSignature:

    def test_signature_created(self, db, branch, user):
        from audit.utils import create_signature
        sig = create_signature(
            signer=user,
            meaning='approved',
            payload_data={'unit_did': 'TEST000001', 'patient_id': 1},
            reauth_at=timezone.now(),
        )
        assert sig.pk is not None
        assert sig.signer == user

    def test_signature_has_payload_hash(self, db, branch, user):
        from audit.utils import create_signature
        sig = create_signature(
            signer=user,
            meaning='approved',
            payload_data={'action': 'crossmatch_override'},
            reauth_at=timezone.now(),
        )
        assert sig.signed_payload_hash
        assert len(sig.signed_payload_hash) == 64

    def test_two_signatures_with_different_payloads_have_different_hashes(self, db, branch, user):
        from audit.utils import create_signature
        s1 = create_signature(signer=user, meaning='approved',
                               payload_data={'id': 1}, reauth_at=timezone.now())
        s2 = create_signature(signer=user, meaning='approved',
                               payload_data={'id': 2}, reauth_at=timezone.now())
        assert s1.signed_payload_hash != s2.signed_payload_hash


class TestAuditedActions:

    def test_unit_transition_creates_audit_entry(self, db, branch, user):
        from audit.models import AuditLog
        from inventory.state_machine import seed_transitions, transition_unit
        from tests.conftest import DonorFactory, DonationFactory, BloodUnitFactory
        seed_transitions()
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='quarantined', owner_branch=branch)
        before_count = AuditLog.objects.count()
        transition_unit(unit, 'in_testing', actor=user, reason='TTI batch')
        assert AuditLog.objects.count() > before_count

    def test_explicit_write_audit_creates_entry(self, db, branch, user):
        from audit.models import AuditLog
        from audit.utils import write_audit
        before_count = AuditLog.objects.count()
        write_audit(
            actor=user,
            action='nc.created',
            entity_table='quality_nonconformance',
            entity_id=999,
            branch=branch,
        )
        assert AuditLog.objects.count() == before_count + 1
