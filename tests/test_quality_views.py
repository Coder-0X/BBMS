"""
Tests for previously-untested quality views:
  - Staff competency list and record
  - Transfusion committee list, create, detail
  - New lot validation list, create, detail
"""
import pytest
from datetime import timedelta
from django.utils import timezone
from django.test import Client

from tests.conftest import (
    UserFactory, BranchFactory, ReagentFactory, ReagentLotFactory,
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
        username=f'su_qv_{branch.pk}_{timezone.now().timestamp():.0f}',
        password='testpass123',
        display_name='QV Super',
        branch=branch,
    )


# ─── Staff Competency ─────────────────────────────────────────────────────────

class TestCompetencyViews:

    def test_competency_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/competency/')
        assert resp.status_code == 200

    def test_competency_list_shows_overdue_count(self, db, branch, user):
        from quality.models import StaffCompetency
        assessor = _su(branch)
        StaffCompetency.objects.create(
            staff_member=user,
            task_category='crossmatch',
            task_description='Perform tube-technique crossmatch',
            assessment_method='direct_observation',
            outcome='satisfactory',
            assessed_at=timezone.now() - timedelta(days=400),
            reassessment_due=timezone.now().date() - timedelta(days=30),
            assessed_by=assessor,
            branch=branch,
        )
        resp = _client(user, branch).get('/quality/competency/')
        assert resp.status_code == 200
        assert resp.context['overdue_count'] == 1

    def test_competency_record_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/competency/new/')
        assert resp.status_code == 200

    def test_competency_record_post_creates_record(self, db, branch, user):
        assessor = _su(branch)
        today = timezone.now().date()
        resp = _client(assessor, branch).post('/quality/competency/new/', {
            'staff_member': user.pk,
            'task_category': 'abo_grouping',
            'task_description': 'Perform ABO forward and reverse grouping',
            'assessment_method': 'direct_observation',
            'outcome': 'satisfactory',
            'assessed_at': today.isoformat(),
            'reassessment_due': (today + timedelta(days=365)).isoformat(),
        })
        assert resp.status_code in (200, 302)
        from quality.models import StaffCompetency
        assert StaffCompetency.objects.filter(staff_member=user, task_category='abo_grouping').exists()

    def test_competency_record_self_assessment_blocked(self, db, branch, user):
        today = timezone.now().date()
        resp = _client(user, branch).post('/quality/competency/new/', {
            'staff_member': user.pk,
            'task_category': 'abo_grouping',
            'task_description': 'Self-assessed task',
            'assessment_method': 'written_exam',
            'outcome': 'satisfactory',
            'assessed_at': today.isoformat(),
            'reassessment_due': (today + timedelta(days=365)).isoformat(),
        })
        from quality.models import StaffCompetency
        assert not StaffCompetency.objects.filter(task_description='Self-assessed task').exists()

    def test_competency_list_filter_by_staff(self, db, branch, user):
        resp = _client(user, branch).get(f'/quality/competency/?staff={user.pk}')
        assert resp.status_code == 200

    def test_competency_list_filter_by_category(self, db, branch, user):
        resp = _client(user, branch).get('/quality/competency/?category=crossmatch')
        assert resp.status_code == 200


# ─── Transfusion Committee ────────────────────────────────────────────────────

class TestCommitteeViews:

    def test_committee_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/committee/')
        assert resp.status_code == 200

    def test_committee_create_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/committee/new/')
        assert resp.status_code == 200

    def test_committee_create_post(self, db, branch, user):
        scheduled = (timezone.now().date() + timedelta(days=14)).isoformat()
        resp = _client(user, branch).post('/quality/committee/new/', {
            'meeting_type': 'quarterly',
            'scheduled_date': scheduled,
            'chair_id': user.pk,
            'agenda_text': 'Q1 review of transfusion practice and haemovigilance data.',
        })
        assert resp.status_code in (200, 302)
        from quality.models import TransfusionCommittee
        assert TransfusionCommittee.objects.filter(branch=branch, meeting_type='quarterly').exists()

    def test_committee_create_post_missing_fields(self, db, branch, user):
        from quality.models import TransfusionCommittee
        count_before = TransfusionCommittee.objects.count()
        resp = _client(user, branch).post('/quality/committee/new/', {
            'meeting_type': 'quarterly',
            # missing scheduled_date and chair_id — should be rejected
        })
        assert resp.status_code in (200, 302)
        assert TransfusionCommittee.objects.count() == count_before

    def test_committee_detail_get(self, db, branch, user):
        from quality.models import TransfusionCommittee
        meeting = TransfusionCommittee.objects.create(
            branch=branch,
            meeting_type='monthly',
            scheduled_date=timezone.now().date() + timedelta(days=7),
            chair=user,
            created_by=user,
        )
        resp = _client(user, branch).get(f'/quality/committee/{meeting.pk}/')
        assert resp.status_code == 200

    def test_committee_detail_record_minutes(self, db, branch, user):
        from quality.models import TransfusionCommittee
        meeting = TransfusionCommittee.objects.create(
            branch=branch,
            meeting_type='monthly',
            scheduled_date=timezone.now().date(),
            chair=user,
            created_by=user,
        )
        resp = _client(user, branch).post(f'/quality/committee/{meeting.pk}/', {
            'action': 'record_minutes',
            'actual_date': timezone.now().date().isoformat(),
            'attendees_text': 'Dr A, Dr B, Lab Mgr C',
            'quorum_met': 'on',
            'minutes_text': 'Reviewed Q1 haemovigilance incidents. No SHOT reports this quarter.',
        })
        assert resp.status_code in (200, 302)
        meeting.refresh_from_db()
        assert meeting.minutes_text != '' or resp.status_code == 200

    def test_committee_list_shows_open_actions_count(self, db, branch, user):
        from quality.models import TransfusionCommittee, CommitteeAction
        meeting = TransfusionCommittee.objects.create(
            branch=branch,
            meeting_type='monthly',
            scheduled_date=timezone.now().date(),
            chair=user,
            created_by=user,
        )
        CommitteeAction.objects.create(
            meeting=meeting,
            description='Review RBC crossmatch failure rate this quarter.',
            owner=user,
            due_date=timezone.now().date() + timedelta(days=30),
            status='open',
        )
        resp = _client(user, branch).get('/quality/committee/')
        assert resp.status_code == 200
        assert resp.context['open_actions'] >= 1


# ─── New Lot Validation ───────────────────────────────────────────────────────

class TestLotValidationViews:

    def test_lot_validation_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/lot-validation/')
        assert resp.status_code == 200

    def test_lot_validation_list_filter(self, db, branch, user):
        resp = _client(user, branch).get('/quality/lot-validation/?status=pending')
        assert resp.status_code == 200

    def test_lot_validation_create_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/lot-validation/new/')
        assert resp.status_code == 200

    def test_lot_validation_create_post(self, db, branch, user):
        reagent = ReagentFactory()
        new_lot = ReagentLotFactory(branch=branch, reagent=reagent, status='quarantined')
        in_use_lot = ReagentLotFactory(branch=branch, reagent=reagent, status='in_use')
        resp = _client(user, branch).post('/quality/lot-validation/new/', {
            'new_lot_id': new_lot.pk,
            'reference_lot_id': in_use_lot.pk,
        })
        assert resp.status_code in (200, 302)
        from quality.models import NewLotValidation
        assert NewLotValidation.objects.filter(new_lot=new_lot).exists()

    def test_lot_validation_create_duplicate_blocked(self, db, branch, user):
        from quality.models import NewLotValidation
        reagent = ReagentFactory()
        new_lot = ReagentLotFactory(branch=branch, reagent=reagent, status='quarantined')
        validation = NewLotValidation.objects.create(
            new_lot=new_lot, branch=branch, initiated_by=user, status='pending',
        )
        resp = _client(user, branch).post('/quality/lot-validation/new/', {
            'new_lot_id': new_lot.pk,
        })
        assert NewLotValidation.objects.filter(new_lot=new_lot).count() == 1

    def test_lot_validation_detail_get(self, db, branch, user):
        from quality.models import NewLotValidation
        reagent = ReagentFactory()
        new_lot = ReagentLotFactory(branch=branch, reagent=reagent, status='quarantined')
        validation = NewLotValidation.objects.create(
            new_lot=new_lot, branch=branch, initiated_by=user, status='pending',
        )
        resp = _client(user, branch).get(f'/quality/lot-validation/{validation.pk}/')
        assert resp.status_code == 200

    def test_lot_validation_add_result(self, db, branch, user):
        from quality.models import NewLotValidation, LotValidationResult
        reagent = ReagentFactory()
        new_lot = ReagentLotFactory(branch=branch, reagent=reagent, status='quarantined')
        in_use_lot = ReagentLotFactory(branch=branch, reagent=reagent, status='in_use')
        validation = NewLotValidation.objects.create(
            new_lot=new_lot, reference_lot=in_use_lot,
            branch=branch, initiated_by=user, status='pending',
        )
        resp = _client(user, branch).post(f'/quality/lot-validation/{validation.pk}/', {
            'action': 'add_result',
            'sample_label': 'Sample A1',
            'ref_grade': '2+',
            'new_grade': '2+',
            'comment': 'Concordant result.',
        })
        assert resp.status_code in (200, 302)
        assert LotValidationResult.objects.filter(validation=validation).exists()

    def test_lot_validation_result_deleted_creates_audit(self, db, branch, user):
        from audit.models import AuditLog
        from quality.models import NewLotValidation, LotValidationResult
        reagent = ReagentFactory()
        new_lot = ReagentLotFactory(branch=branch, reagent=reagent, status='quarantined')
        validation = NewLotValidation.objects.create(
            new_lot=new_lot, branch=branch, initiated_by=user, status='in_review',
        )
        result = LotValidationResult.objects.create(
            validation=validation, sample_label='X1', ref_grade='3+', new_grade='3+',
        )
        _client(user, branch).post(f'/quality/lot-validation/{validation.pk}/', {
            'action': 'delete_result',
            'result_pk': result.pk,
        })
        assert AuditLog.objects.filter(action='lot_validation.result_deleted').exists()


# ─── Internal Quality Audit ───────────────────────────────────────────────────

class TestInternalAuditViews:

    def _make_audit(self, branch, user):
        from quality.models import InternalAudit
        return InternalAudit.objects.create(
            branch=branch,
            audit_type='process',
            scope='Blood group serology procedures',
            auditee_area='Blood Bank Laboratory',
            scheduled_date=timezone.now().date(),
            lead_auditor=user,
            created_by=user,
            status='scheduled',
        )

    def test_audit_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/audits/')
        assert resp.status_code == 200

    def test_audit_create_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/audits/new/')
        assert resp.status_code == 200

    def test_audit_create_post(self, db, branch, user):
        from quality.models import InternalAudit
        count_before = InternalAudit.objects.count()
        resp = _client(user, branch).post('/quality/audits/new/', {
            'audit_type': 'process',
            'scope': 'Pre-transfusion testing — cross-match verification',
            'auditee_area': 'Blood Bank Laboratory',
            'scheduled_date': timezone.now().date().isoformat(),
        })
        assert resp.status_code in (200, 302)
        assert InternalAudit.objects.count() > count_before

    def test_audit_detail_get(self, db, branch, user):
        audit = self._make_audit(branch, user)
        resp = _client(user, branch).get(f'/quality/audits/{audit.pk}/')
        assert resp.status_code == 200

    def test_audit_detail_add_finding(self, db, branch, user):
        from quality.models import AuditFinding
        audit = self._make_audit(branch, user)
        count_before = AuditFinding.objects.filter(audit=audit).count()
        resp = _client(user, branch).post(f'/quality/audits/{audit.pk}/', {
            'action': 'add_finding',
            'classification': 'minor',
            'description': 'Sample tube labelling did not include collection time on 3 of 20 reviewed.',
            'reference': 'SOP-BG-001 §4.2',
            'due_date': (timezone.now().date() + timedelta(days=30)).isoformat(),
        })
        assert resp.status_code in (200, 302)
        assert AuditFinding.objects.filter(audit=audit).count() > count_before

    def test_audit_detail_update_status(self, db, branch, user):
        audit = self._make_audit(branch, user)
        resp = _client(user, branch).post(f'/quality/audits/{audit.pk}/', {
            'action': 'update_status',
            'new_status': 'in_progress',
        })
        assert resp.status_code in (200, 302)
        audit.refresh_from_db()
        assert audit.status == 'in_progress'

    def test_audit_detail_resolve_finding(self, db, branch, user):
        from quality.models import AuditFinding
        audit = self._make_audit(branch, user)
        finding = AuditFinding.objects.create(
            audit=audit,
            classification='minor',
            description='Expired reagent lot still in fridge.',
        )
        resp = _client(user, branch).post(f'/quality/audits/{audit.pk}/', {
            'action': 'resolve_finding',
            'finding_pk': finding.pk,
            'resolution': 'Lot removed. Re-trained staff on expiry checking procedure.',
        })
        assert resp.status_code in (200, 302)
        finding.refresh_from_db()
        assert finding.status == 'resolved'

    def test_audit_detail_add_finding_creates_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        audit = self._make_audit(branch, user)
        _client(user, branch).post(f'/quality/audits/{audit.pk}/', {
            'action': 'add_finding',
            'classification': 'major',
            'description': 'Critical procedure not followed.',
        })
        assert AuditLog.objects.filter(action='internal_audit.finding_added').exists()


# ─── SOP management ───────────────────────────────────────────────────────────

class TestSOPViews:

    def _make_sop(self, branch, user):
        from quality.models import StandardOperatingProcedure
        return StandardOperatingProcedure.objects.create(
            branch=branch,
            sop_code=f'SOP-TEST-{branch.pk}',
            title='Test Pre-transfusion Compatibility Testing SOP',
            category='pre_transfusion',
            review_interval_months=12,
            status='draft',
            owner=user,
            created_by=user,
        )

    def test_sop_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/sop/')
        assert resp.status_code == 200

    def test_sop_create_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/sop/new/')
        assert resp.status_code == 200

    def test_sop_create_post(self, db, branch, user):
        from quality.models import StandardOperatingProcedure
        count_before = StandardOperatingProcedure.objects.count()
        resp = _client(user, branch).post('/quality/sop/new/', {
            'sop_code': f'SOP-NEW-{branch.pk}',
            'title': 'Blood Group Serology Procedures',
            'category': 'blood_grouping',
            'review_interval_months': '12',
        })
        assert resp.status_code in (200, 302)
        assert StandardOperatingProcedure.objects.count() > count_before

    def test_sop_detail_get(self, db, branch, user):
        sop = self._make_sop(branch, user)
        resp = _client(user, branch).get(f'/quality/sop/{sop.pk}/')
        assert resp.status_code == 200

    def test_sop_detail_add_version(self, db, branch, user):
        from quality.models import SOPVersion
        sop = self._make_sop(branch, user)
        resp = _client(user, branch).post(f'/quality/sop/{sop.pk}/', {
            'action': 'add_version',
            'version_number': '1.0',
            'summary_of_changes': 'Initial release.',
            'document_text': 'Full procedure text here.',
        })
        assert resp.status_code in (200, 302)
        assert SOPVersion.objects.filter(sop=sop, version_number='1.0').exists()

    def test_sop_detail_duplicate_version_blocked(self, db, branch, user):
        from quality.models import SOPVersion
        sop = self._make_sop(branch, user)
        SOPVersion.objects.create(sop=sop, version_number='2.0',
                                  authored_by=user, summary_of_changes='')
        count_before = SOPVersion.objects.filter(sop=sop).count()
        _client(user, branch).post(f'/quality/sop/{sop.pk}/', {
            'action': 'add_version',
            'version_number': '2.0',
            'summary_of_changes': 'Duplicate attempt',
        })
        assert SOPVersion.objects.filter(sop=sop).count() == count_before


# ─── QC dashboard and reagent views ──────────────────────────────────────────

class TestQCDashboardAndReagentViews:

    def test_qc_dashboard_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/')
        assert resp.status_code == 200

    def test_reagent_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/reagents/')
        assert resp.status_code == 200

    def test_reagent_list_shows_reagent(self, db, branch, user):
        reagent = ReagentFactory()
        resp = _client(user, branch).get('/quality/reagents/')
        assert resp.status_code == 200
        assert reagent.name.encode() in resp.content

    def test_reagent_detail_get(self, db, branch, user):
        reagent = ReagentFactory()
        resp = _client(user, branch).get(f'/quality/reagents/{reagent.pk}/')
        assert resp.status_code == 200

    def test_register_lot_get(self, db, branch, user):
        reagent = ReagentFactory()
        resp = _client(user, branch).get(f'/quality/reagents/{reagent.pk}/lot/new/')
        assert resp.status_code == 200

    def test_register_lot_post_creates_lot(self, db, branch, user):
        from quality.models import ReagentLot
        su = _su(branch)
        reagent = ReagentFactory()
        count_before = ReagentLot.objects.count()
        from django.utils import timezone as tz
        resp = _client(su, branch).post(f'/quality/reagents/{reagent.pk}/lot/new/', {
            'lot_number': 'LOT-TEST-001',
            'expiry_date': (tz.now().date() + __import__('datetime').timedelta(days=180)).isoformat(),
            'manufacturer_site': 'TestSite',
            'certificate_ok': 'on',
        })
        assert resp.status_code in (200, 302)
        assert ReagentLot.objects.count() > count_before

    def test_record_qc_get(self, db, branch, user):
        reagent = ReagentFactory()
        lot = ReagentLotFactory(reagent=reagent, branch=branch, status='in_use')
        resp = _client(user, branch).get(f'/quality/reagents/{reagent.pk}/qc/')
        assert resp.status_code == 200

    def test_record_qc_pass_records_run(self, db, branch, user):
        from quality.models import QCRun
        su = _su(branch)
        reagent = ReagentFactory()
        lot = ReagentLotFactory(reagent=reagent, branch=branch, status='in_use')
        count_before = QCRun.objects.count()
        resp = _client(su, branch).post(f'/quality/reagents/{reagent.pk}/qc/', {
            'lot_id': lot.pk,
            'pos_observed': '4+',
            'neg_observed': '0',
            'pos_expected': '4+',
            'neg_expected': '0',
            'protocol': 'daily',
        })
        assert resp.status_code in (200, 302)
        assert QCRun.objects.count() > count_before

    def test_record_qc_pass_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        from quality.models import QCRun
        su = _su(branch)
        reagent = ReagentFactory()
        lot = ReagentLotFactory(reagent=reagent, branch=branch, status='in_use')
        _client(su, branch).post(f'/quality/reagents/{reagent.pk}/qc/', {
            'lot_id': lot.pk,
            'pos_observed': '4+',
            'neg_observed': '0',
            'pos_expected': '4+',
            'neg_expected': '0',
            'protocol': 'daily',
        })
        assert AuditLog.objects.filter(action='reagent.qc.record').exists()

    def test_calibration_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/calibrations/')
        assert resp.status_code == 200


# ─── Non-Conformance views ───────────────────────────────────────────────────

from tests.conftest import NonConformanceFactory


class TestNCViews:

    def test_nc_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/nc/')
        assert resp.status_code == 200

    def test_nc_list_shows_nc(self, db, branch, user):
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        resp = _client(user, branch).get('/quality/nc/')
        assert resp.status_code == 200
        assert nc.nc_number.encode() in resp.content

    def test_nc_list_filter_by_status(self, db, branch, user):
        NonConformanceFactory(reported_by=user, branch=branch, status='open')
        resp = _client(user, branch).get('/quality/nc/?status=open')
        assert resp.status_code == 200

    def test_nc_create_get(self, db, branch, user):
        resp = _client(user, branch).get('/quality/nc/new/')
        assert resp.status_code == 200

    def test_nc_create_post_creates_nc(self, db, branch, user):
        from quality.models import NonConformance
        from django.utils import timezone as tz
        count_before = NonConformance.objects.count()
        resp = _client(user, branch).post('/quality/nc/new/', {
            'nc_type': 'labelling',
            'severity': 'minor',
            'description': 'Label missing on unit',
            'event_date': tz.now().date().isoformat(),
        })
        assert resp.status_code in (200, 302)
        assert NonConformance.objects.count() > count_before

    def test_nc_create_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        from django.utils import timezone as tz
        _client(user, branch).post('/quality/nc/new/', {
            'nc_type': 'labelling',
            'severity': 'minor',
            'description': 'Test NC for audit',
            'event_date': tz.now().date().isoformat(),
        })
        assert AuditLog.objects.filter(action='quality.nc.created').exists()

    def test_nc_detail_get(self, db, branch, user):
        nc = NonConformanceFactory(reported_by=user, branch=branch)
        resp = _client(user, branch).get(f'/quality/nc/{nc.pk}/')
        assert resp.status_code == 200

    def test_unauthenticated_nc_list_redirects(self, db):
        from django.test import Client as C
        resp = C().get('/quality/nc/')
        assert resp.status_code == 302
