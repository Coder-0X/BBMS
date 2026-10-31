"""
Quality management tests — NC lifecycle, reagent lots, SOP, CorrectiveAction.
Run: pytest tests/test_quality.py -v
"""
import pytest
from datetime import timedelta
from django.utils import timezone

from tests.conftest import (
    UserFactory, BranchFactory, NonConformanceFactory,
    ReagentFactory, ReagentLotFactory,
)


# ─── NonConformance lifecycle ─────────────────────────────────────────────────

class TestNcLifecycle:

    def test_nc_opens_with_status_open(self, db, branch, user):
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        assert nc.status == 'open'

    def test_nc_can_be_assigned(self, db, branch, user):
        assignee = UserFactory(branch=branch)
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        nc.assigned_to = assignee
        nc.save()
        nc.refresh_from_db()
        assert nc.assigned_to == assignee

    def test_nc_status_transitions(self, db, branch, user):
        nc = NonConformanceFactory(reported_by=user, branch=branch, status='open')
        for status in ('under_review', 'capa_open', 'capa_verify', 'closed'):
            nc.status = status
            nc.save()
        nc.refresh_from_db()
        assert nc.status == 'closed'

    def test_nc_number_auto_assigned(self, db, branch, user):
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        assert nc.nc_number
        assert nc.nc_number.startswith('NC-')

    def test_nc_number_unique(self, db, branch, user):
        nc1 = NonConformanceFactory(reported_by=user, branch=branch)
        nc2 = NonConformanceFactory(reported_by=user, branch=branch)
        assert nc1.nc_number != nc2.nc_number


# ─── CorrectiveAction (CAPA) ──────────────────────────────────────────────────

class TestCorrectiveAction:

    def test_ca_linked_to_nc(self, db, branch, user):
        from quality.models import CorrectiveAction
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        ca = CorrectiveAction.objects.create(
            nc=nc,
            action_type='corrective',
            description='Retrain staff on labelling procedure',
            assigned_to=user,
            due_date=timezone.now().date() + timedelta(days=30),
        )
        assert ca.nc == nc
        assert ca.status == 'assigned'

    def test_ca_can_be_completed(self, db, branch, user):
        from quality.models import CorrectiveAction
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        ca = CorrectiveAction.objects.create(
            nc=nc,
            action_type='corrective',
            description='Update SOP BB-001',
            assigned_to=user,
            due_date=timezone.now().date() + timedelta(days=14),
        )
        ca.status = 'completed'
        ca.completed_at = timezone.now()
        ca.completed_by = user
        ca.save()
        ca.refresh_from_db()
        assert ca.status == 'completed'

    def test_ca_can_be_verified_effective(self, db, branch, user):
        from quality.models import CorrectiveAction
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        ca = CorrectiveAction.objects.create(
            nc=nc,
            action_type='preventive',
            description='Implement dual-check on specimen labelling',
            assigned_to=user,
            due_date=timezone.now().date() + timedelta(days=21),
        )
        ca.status = 'verified'
        ca.verified_at = timezone.now()
        ca.verified_by = user
        ca.verification_notes = 'Follow-up audit shows zero recurrence'
        ca.save()
        ca.refresh_from_db()
        assert ca.status == 'verified'

    def test_ca_is_overdue_when_past_due_date(self, db, branch, user):
        from quality.models import CorrectiveAction
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        ca = CorrectiveAction.objects.create(
            nc=nc,
            action_type='corrective',
            description='Overdue action',
            assigned_to=user,
            due_date=timezone.now().date() - timedelta(days=1),
        )
        assert ca.is_overdue()

    def test_completed_ca_not_overdue(self, db, branch, user):
        from quality.models import CorrectiveAction
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        ca = CorrectiveAction.objects.create(
            nc=nc,
            action_type='corrective',
            description='Completed on time',
            assigned_to=user,
            due_date=timezone.now().date() - timedelta(days=1),
            status='completed',
        )
        assert not ca.is_overdue()


# ─── Reagent lot validation (New Lot Validation) ─────────────────────────────

class TestReagentLotValidation:

    def test_lot_in_use_status(self, db):
        lot = ReagentLotFactory(status='in_use')
        assert lot.status == 'in_use'

    def test_lot_expiry_check(self, db):
        expired_lot = ReagentLotFactory(
            expiry_date=timezone.now().date() - timedelta(days=1),
            status='in_use',
        )
        assert expired_lot.is_expired()  # method, not property

    def test_lot_not_expired_when_in_future(self, db):
        lot = ReagentLotFactory(
            expiry_date=timezone.now().date() + timedelta(days=180),
        )
        assert not lot.is_expired()

    def test_qc_run_pass_recorded(self, db, branch, user):
        from quality.models import QCRun
        lot = ReagentLotFactory(branch=branch)
        run = QCRun.objects.create(
            reagent=lot.reagent,
            lot=lot,
            branch=branch,
            performed_by=user,
            started_at=timezone.now(),
            completed_at=timezone.now(),
            overall_pass=True,
        )
        assert run.overall_pass is True
        assert run.pk is not None

    def test_qc_run_fail_recorded(self, db, branch, user):
        from quality.models import QCRun
        lot = ReagentLotFactory(branch=branch, status='in_use')
        run = QCRun.objects.create(
            reagent=lot.reagent,
            lot=lot,
            branch=branch,
            performed_by=user,
            started_at=timezone.now(),
            completed_at=timezone.now(),
            overall_pass=False,
            failure_action='Quarantine lot pending investigation',
        )
        assert run.overall_pass is False

    def test_reagent_qc_status_overdue_when_no_runs(self, db, branch):
        reagent = ReagentFactory()
        assert reagent.qc_status(branch_id=branch.pk) == 'overdue'

    def test_reagent_qc_status_pass_after_recent_run(self, db, branch, user):
        from quality.models import QCRun
        lot = ReagentLotFactory(branch=branch)
        QCRun.objects.create(
            reagent=lot.reagent, lot=lot, branch=branch,
            performed_by=user,
            started_at=timezone.now(), completed_at=timezone.now(),
            overall_pass=True,
        )
        assert lot.reagent.qc_status(branch_id=branch.pk) == 'pass'

    def test_reagent_qc_status_fail_after_failed_run(self, db, branch, user):
        from quality.models import QCRun
        lot = ReagentLotFactory(branch=branch)
        QCRun.objects.create(
            reagent=lot.reagent, lot=lot, branch=branch,
            performed_by=user,
            started_at=timezone.now(), completed_at=timezone.now(),
            overall_pass=False,
        )
        assert lot.reagent.qc_status(branch_id=branch.pk) == 'fail'


# ─── SOP management ──────────────────────────────────────────────────────────

class TestSopModel:

    def test_sop_created(self, db, branch, user):
        from quality.models import StandardOperatingProcedure
        sop = StandardOperatingProcedure.objects.create(
            sop_code='BB-SOP-001',
            title='Pre-transfusion Testing Procedure',
            category='pre_transfusion',
            owner=user,
            branch=branch,
            status='active',
            created_by=user,
        )
        assert sop.pk is not None
        assert sop.sop_code == 'BB-SOP-001'

    def test_sop_version_created(self, db, branch, user):
        from quality.models import StandardOperatingProcedure, SOPVersion
        sop = StandardOperatingProcedure.objects.create(
            sop_code='BB-SOP-002',
            title='Donor Selection Criteria',
            category='donor_screening',
            owner=user,
            branch=branch,
            status='active',
            created_by=user,
        )
        v1 = SOPVersion.objects.create(
            sop=sop,
            version_number='1.0',
            authored_by=user,
            status='approved',
        )
        assert v1.sop == sop
        assert v1.version_number == '1.0'

    def test_sop_two_versions(self, db, branch, user):
        from quality.models import StandardOperatingProcedure, SOPVersion
        sop = StandardOperatingProcedure.objects.create(
            sop_code='BB-SOP-003',
            title='Component Preparation',
            category='component_prep',
            owner=user,
            branch=branch,
            status='active',
            created_by=user,
        )
        SOPVersion.objects.create(sop=sop, version_number='1.0', authored_by=user, status='retired')
        SOPVersion.objects.create(sop=sop, version_number='2.0', authored_by=user, status='approved')
        assert sop.versions.count() == 2

    def test_sop_review_due_date(self, db, branch, user):
        from quality.models import StandardOperatingProcedure
        review_date = timezone.now().date() + timedelta(days=365)
        sop = StandardOperatingProcedure.objects.create(
            sop_code='BB-SOP-004',
            title='Cold Chain Monitoring',
            category='cold_chain',
            next_review_due=review_date,
            owner=user,
            branch=branch,
            status='active',
            created_by=user,
        )
        assert sop.next_review_due == review_date

    def test_overdue_review_detected(self, db, branch, user):
        from quality.models import StandardOperatingProcedure
        sop = StandardOperatingProcedure.objects.create(
            sop_code='BB-SOP-005',
            title='Emergency Release',
            category='emergency',
            next_review_due=timezone.now().date() - timedelta(days=1),
            owner=user,
            branch=branch,
            status='active',
            created_by=user,
        )
        assert sop.is_overdue_review()


# ─── Internal Audit Findings ──────────────────────────────────────────────────

class TestAuditFindingModel:

    def _make_internal_audit(self, branch, user):
        from quality.models import InternalAudit
        return InternalAudit.objects.create(
            audit_type='process',
            scope='Pre-transfusion testing compliance check',
            branch=branch,
            lead_auditor=user,
            scheduled_date=timezone.now().date(),
            auditee_area='Blood Bank Laboratory',
            created_by=user,
        )

    def test_audit_finding_created(self, db, branch, user):
        from quality.models import AuditFinding
        audit = self._make_internal_audit(branch, user)
        finding = AuditFinding.objects.create(
            audit=audit,
            classification='major',
            description='Blood group results not transcribed within 30 minutes per SOP',
            status='open',
        )
        assert finding.pk is not None
        assert finding.classification == 'major'

    def test_major_finding_is_classified_correctly(self, db, branch, user):
        from quality.models import AuditFinding
        audit = self._make_internal_audit(branch, user)
        finding = AuditFinding.objects.create(
            audit=audit,
            classification='major',
            description='Double ABO rule not followed for 3 consecutive patients',
            status='open',
        )
        assert finding.classification == 'major'
        assert finding.status == 'open'

    def test_minor_finding_created(self, db, branch, user):
        from quality.models import AuditFinding
        audit = self._make_internal_audit(branch, user)
        finding = AuditFinding.objects.create(
            audit=audit,
            classification='minor',
            description='Temperature log sheet missing one entry',
            status='open',
        )
        assert finding.classification == 'minor'

    def test_finding_overdue_when_past_due(self, db, branch, user):
        from quality.models import AuditFinding
        audit = self._make_internal_audit(branch, user)
        finding = AuditFinding.objects.create(
            audit=audit,
            classification='major',
            description='Overdue finding',
            status='open',
            due_date=timezone.now().date() - timedelta(days=1),
        )
        assert finding.is_overdue()
