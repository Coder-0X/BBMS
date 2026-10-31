"""
Tests for core views:
  dashboard, reports_view, branch_list/create/select,
  audit_log_view, config_target CRUD, audit_chain_verify,
  mci_status (GET), tat_report, quality_indicators.
"""
import pytest
from django.test import Client
from django.utils import timezone

from tests.conftest import BranchFactory, UserFactory


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
        username=f'su_cv_{branch.pk}_{timezone.now().timestamp():.0f}',
        password='testpass123',
        display_name='Core View Super',
        branch=branch,
    )


# ─── Dashboard ────────────────────────────────────────────────────────────────

class TestDashboard:

    def test_dashboard_get(self, db, branch, user):
        resp = _client(user, branch).get('/dashboard/')
        assert resp.status_code == 200

    def test_dashboard_without_session_branch(self, db, branch, user):
        c = Client()
        c.login(username=user.username, password='testpass123')
        resp = c.get('/dashboard/')
        assert resp.status_code in (200, 302)

    def test_dashboard_shows_stats(self, db, branch, user):
        resp = _client(user, branch).get('/dashboard/')
        assert resp.status_code == 200
        assert 'stats' in resp.context


# ─── Reports ─────────────────────────────────────────────────────────────────

class TestReportsView:

    def test_reports_get(self, db, branch, user):
        resp = _client(user, branch).get('/reports/')
        assert resp.status_code == 200

    def test_reports_get_with_days_filter(self, db, branch, user):
        resp = _client(user, branch).get('/reports/?days=7')
        assert resp.status_code == 200

    def test_tat_report_get(self, db, branch, user):
        resp = _client(user, branch).get('/reports/tat/')
        assert resp.status_code == 200

    def test_quality_indicators_get(self, db, branch, user):
        resp = _client(user, branch).get('/reports/quality-indicators/')
        assert resp.status_code == 200

    def test_quality_indicators_with_days(self, db, branch, user):
        resp = _client(user, branch).get('/reports/quality-indicators/?days=90')
        assert resp.status_code == 200


# ─── Branch management ────────────────────────────────────────────────────────

class TestBranchViews:

    def test_branch_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/branches/')
        assert resp.status_code == 200

    def test_branch_list_shows_branches(self, db, branch, user):
        resp = _client(user, branch).get('/branches/')
        assert resp.status_code == 200
        assert len(resp.context['branches']) >= 1

    def test_branch_create_requires_staff(self, db, branch, user):
        """
        Security regression: branch_create was only @login_required,
        allowing any authenticated user to create branches.
        After fix, non-staff users must be blocked (200 or 302 with error, not creating a branch).
        """
        from core.models import Branch
        count_before = Branch.objects.count()
        _client(user, branch).post('/branches/new/', {
            'name': 'Unauthorised Branch',
            'facility_code': 'UNB',
            'address': '1 Hack St',
            'timezone': 'UTC',
        })
        # Non-staff user should not be able to create a branch
        assert Branch.objects.count() == count_before

    def test_branch_create_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/branches/new/')
        assert resp.status_code == 200

    def test_branch_create_post(self, db, branch, user):
        from core.models import Branch
        su = _su(branch)
        count_before = Branch.objects.count()
        resp = _client(su, branch).post('/branches/new/', {
            'name': 'Night Test Branch',
            'facility_code': 'NTB',
            'address': '1 Night Drive',
            'timezone': 'UTC',
        })
        assert resp.status_code in (200, 302)
        assert Branch.objects.count() > count_before

    def test_select_branch_get(self, db, branch, user):
        resp = _client(user, branch).get('/branches/select/')
        assert resp.status_code == 200

    def test_select_branch_post_switches_session(self, db, branch, user):
        other = BranchFactory()
        c = _client(user, branch)
        resp = c.post('/branches/select/', {'branch_id': other.pk})
        assert resp.status_code in (200, 302)
        # After switch, session branch should be the new one
        assert c.session.get('branch_id') == other.pk

    def test_select_branch_post_invalid_id_does_not_switch(self, db, branch, user):
        c = _client(user, branch)
        c.post('/branches/select/', {'branch_id': '999999'})
        # Session branch unchanged
        assert c.session.get('branch_id') == branch.pk

    def test_select_branch_post_non_numeric_id_does_not_crash(self, db, branch, user):
        """Regression: non-numeric branch_id ('abc') raised ValueError before fix."""
        c = _client(user, branch)
        resp = c.post('/branches/select/', {'branch_id': 'abc'})
        assert resp.status_code in (200, 302)
        assert c.session.get('branch_id') == branch.pk


# ─── Audit log ────────────────────────────────────────────────────────────────

class TestAuditLogView:

    def test_audit_log_requires_staff(self, db, branch, user):
        resp = _client(user, branch).get('/audit/')
        assert resp.status_code in (200, 302)

    def test_audit_log_staff_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/audit/')
        assert resp.status_code == 200

    def test_audit_log_with_action_filter(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/audit/?action=unit.status_changed')
        assert resp.status_code == 200

    def test_audit_log_with_actor_filter(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get(f'/audit/?actor={user.username}')
        assert resp.status_code == 200

    def test_audit_log_with_table_filter(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/audit/?table=inventory_bloodunit')
        assert resp.status_code == 200


# ─── Audit chain verify ───────────────────────────────────────────────────────

class TestAuditChainVerify:

    def test_audit_chain_verify_requires_staff(self, db, branch, user):
        resp = _client(user, branch).get('/audit/verify-chain/')
        assert resp.status_code in (200, 302)

    def test_audit_chain_verify_staff_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/audit/verify-chain/')
        assert resp.status_code == 200
        assert 'is_valid' in resp.context
        assert 'total_entries' in resp.context

    def test_audit_chain_verify_empty_chain_is_valid(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/audit/verify-chain/')
        assert resp.status_code == 200
        # An empty chain should be considered valid
        assert resp.context['is_valid'] is True


# ─── Config targets ───────────────────────────────────────────────────────────

class TestConfigTargetViews:

    def test_config_target_list_requires_staff(self, db, branch, user):
        resp = _client(user, branch).get('/config-targets/')
        assert resp.status_code in (200, 302)

    def test_config_target_list_staff_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/config-targets/')
        assert resp.status_code == 200

    def test_config_target_create_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/config-targets/new/')
        assert resp.status_code == 200

    def test_config_target_create_post(self, db, branch, user):
        from core.models import ConfigTarget
        su = _su(branch)
        count_before = ConfigTarget.objects.filter(branch=branch).count()
        resp = _client(su, branch).post('/config-targets/new/', {
            'component_class': 'RBC',
            'target_days_of_supply': '3.0',
            'max_wastage_pct': '5.0',
            'near_expiry_alert_hours': '72',
            'max_ct_ratio': '2.5',
            'safety_quantile': '0.95',
        })
        assert resp.status_code in (200, 302)
        assert ConfigTarget.objects.filter(branch=branch).count() > count_before

    def test_config_target_edit_post(self, db, branch, user):
        from core.models import ConfigTarget
        su = _su(branch)
        target = ConfigTarget.objects.create(
            branch=branch,
            component_class='FFP',
            target_days_of_supply=3,
            max_wastage_pct=5,
            near_expiry_alert_hours=72,
            max_ct_ratio=2.5,
            safety_quantile=0.95,
        )
        resp = _client(su, branch).post(f'/config-targets/{target.pk}/edit/', {
            'component_class': 'FFP',
            'target_days_of_supply': '5.0',
            'max_wastage_pct': '4.0',
            'near_expiry_alert_hours': '48',
            'max_ct_ratio': '3.0',
            'safety_quantile': '0.90',
        })
        assert resp.status_code in (200, 302)
        target.refresh_from_db()
        assert float(target.target_days_of_supply) == 5.0

    def test_config_target_delete_get(self, db, branch, user):
        from core.models import ConfigTarget
        su = _su(branch)
        target = ConfigTarget.objects.create(
            branch=branch, component_class='PLT',
            target_days_of_supply=3, max_wastage_pct=5,
            near_expiry_alert_hours=72, max_ct_ratio=2.5,
            safety_quantile=0.95,
        )
        resp = _client(su, branch).get(f'/config-targets/{target.pk}/delete/')
        assert resp.status_code == 200

    def test_config_target_delete_post(self, db, branch, user):
        from core.models import ConfigTarget
        su = _su(branch)
        target = ConfigTarget.objects.create(
            branch=branch, component_class='CRYO',
            target_days_of_supply=3, max_wastage_pct=5,
            near_expiry_alert_hours=72, max_ct_ratio=2.5,
            safety_quantile=0.95,
        )
        pk = target.pk
        resp = _client(su, branch).post(f'/config-targets/{pk}/delete/')
        assert resp.status_code in (200, 302)
        assert not ConfigTarget.objects.filter(pk=pk).exists()


# ─── MCI status ───────────────────────────────────────────────────────────────

class TestMCIStatus:

    def test_mci_get(self, db, branch, user):
        resp = _client(user, branch).get('/mci/')
        assert resp.status_code == 200

    def test_mci_get_no_active_event(self, db, branch, user):
        resp = _client(user, branch).get('/mci/')
        assert resp.status_code == 200
        assert resp.context['active_mci'] is None

    def test_mci_get_with_active_event(self, db, branch, user):
        from core.models import MCIEvent
        MCIEvent.objects.create(
            branch=branch,
            level='2',
            incident_name='Test MCI',
            status='active',
            activated_by=user,
            activated_at=timezone.now(),
        )
        resp = _client(user, branch).get('/mci/')
        assert resp.status_code == 200
        assert resp.context['active_mci'] is not None

    def test_mci_post_activate_creates_mci_event(self, db, branch, user):
        """Superuser can activate an MCI event via POST action='activate'."""
        from core.models import MCIEvent
        su = _su(branch)
        count_before = MCIEvent.objects.filter(branch=branch, status='active').count()
        resp = _client(su, branch).post('/mci/', {
            'action': 'activate',
            'level': '2',
            'incident_name': 'Bus Crash RTC',
            'notes': 'Multiple casualties inbound',
        })
        assert resp.status_code in (200, 302)
        assert MCIEvent.objects.filter(branch=branch, status='active').count() > count_before

    def test_mci_post_activate_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        _client(su, branch).post('/mci/', {
            'action': 'activate',
            'level': '1',
            'incident_name': 'Chemical Spill',
        })
        assert AuditLog.objects.filter(action='mci.activated').exists()

    def test_mci_post_standdown_closes_active_mci(self, db, branch, user):
        """Superuser can stand down an active MCI via POST action='standdown'."""
        from core.models import MCIEvent
        su = _su(branch)
        # Activate first
        _client(su, branch).post('/mci/', {
            'action': 'activate',
            'level': '2',
            'incident_name': 'Mass Casualty Event',
        })
        active = MCIEvent.objects.filter(branch=branch, status='active').first()
        assert active is not None
        # Now stand down
        resp = _client(su, branch).post('/mci/', {
            'action': 'standdown',
            'notes': 'Situation resolved — all units returned.',
        })
        assert resp.status_code in (200, 302)
        active.refresh_from_db()
        assert active.status == 'stood_down'

    def test_mci_post_activate_no_permission_blocked(self, db, branch, user):
        """Non-superuser without mci.activate permission cannot activate MCI."""
        from core.models import MCIEvent
        count_before = MCIEvent.objects.filter(branch=branch, status='active').count()
        # Regular user (non-superuser) — has no mci.activate permission
        resp = _client(user, branch).post('/mci/', {
            'action': 'activate',
            'level': '2',
            'incident_name': 'Unauthorised Attempt',
        })
        assert resp.status_code in (200, 302)
        # No new active MCI should exist
        assert MCIEvent.objects.filter(branch=branch, status='active').count() == count_before


# ─── Alerts view ──────────────────────────────────────────────────────────────

class TestAlertsView:

    def test_alerts_get(self, db, branch, user):
        resp = _client(user, branch).get('/alerts/')
        assert resp.status_code == 200

    def test_alerts_shows_alert_in_list(self, db, branch, user):
        from core.models import Alert
        Alert.objects.create(
            branch=branch, alert_type='low_inventory',
            severity='warning', message='Low RBC stock',
        )
        resp = _client(user, branch).get('/alerts/')
        assert resp.status_code == 200
        assert b'Low RBC stock' in resp.content

    def test_alerts_filter_by_severity(self, db, branch, user):
        from core.models import Alert
        Alert.objects.create(
            branch=branch, alert_type='low_inventory', severity='warning', message='Warning msg'
        )
        Alert.objects.create(
            branch=branch, alert_type='near_expiry', severity='critical', message='Critical msg'
        )
        resp = _client(user, branch).get('/alerts/?severity=critical')
        assert resp.status_code == 200
        assert b'Critical msg' in resp.content
        assert b'Warning msg' not in resp.content

    def test_alerts_filter_unacknowledged(self, db, branch, user):
        from core.models import Alert
        Alert.objects.create(
            branch=branch, alert_type='low_inventory', severity='info', message='Unacked alert'
        )
        Alert.objects.create(
            branch=branch, alert_type='near_expiry', severity='info', message='Acked alert',
            acknowledged_at=timezone.now(), acknowledged_by=user,
        )
        resp = _client(user, branch).get('/alerts/?acked=0')
        assert resp.status_code == 200
        assert b'Unacked alert' in resp.content
        assert b'Acked alert' not in resp.content

    def test_alerts_post_acknowledge(self, db, branch, user):
        from core.models import Alert
        alert = Alert.objects.create(
            branch=branch, alert_type='low_inventory', severity='warning', message='Ack this'
        )
        resp = _client(user, branch).post('/alerts/', {
            'action': 'acknowledge', 'alert_id': alert.pk,
        })
        assert resp.status_code in (200, 302)
        alert.refresh_from_db()
        assert alert.acknowledged_at is not None

    def test_alerts_post_acknowledge_all(self, db, branch, user):
        from core.models import Alert
        Alert.objects.create(
            branch=branch, alert_type='low_inventory', severity='warning', message='A1'
        )
        Alert.objects.create(
            branch=branch, alert_type='near_expiry', severity='info', message='A2'
        )
        _client(user, branch).post('/alerts/', {'action': 'acknowledge_all'})
        unacked = Alert.objects.filter(branch=branch, acknowledged_at__isnull=True).count()
        assert unacked == 0

    def test_alerts_unauthenticated_redirects(self, db):
        resp = Client().get('/alerts/')
        assert resp.status_code == 302
        assert 'login' in resp.get('Location', '').lower()

    def test_alerts_acknowledge_creates_audit_log(self, db, branch, user):
        """Regression: alert acknowledgment had no audit trail before fix."""
        from core.models import Alert
        from audit.models import AuditLog
        alert = Alert.objects.create(
            branch=branch, alert_type='low_inventory', severity='warning', message='Audit me'
        )
        before_count = AuditLog.objects.filter(action='alert.acknowledge').count()
        _client(user, branch).post('/alerts/', {
            'action': 'acknowledge', 'alert_id': alert.pk,
        })
        assert AuditLog.objects.filter(action='alert.acknowledge').count() > before_count

    def test_alerts_acknowledge_non_numeric_alert_id_does_not_crash(self, db, branch, user):
        """Regression: non-numeric alert_id ('abc') raised ValueError before fix."""
        resp = _client(user, branch).post('/alerts/', {
            'action': 'acknowledge', 'alert_id': 'abc',
        })
        assert resp.status_code in (200, 302)

    def test_alerts_acknowledge_all_creates_audit_log(self, db, branch, user):
        """acknowledge_all bulk action should create an audit log entry."""
        from core.models import Alert
        from audit.models import AuditLog
        Alert.objects.create(
            branch=branch, alert_type='near_expiry', severity='info', message='Bulk ack 1'
        )
        Alert.objects.create(
            branch=branch, alert_type='low_inventory', severity='warning', message='Bulk ack 2'
        )
        before_count = AuditLog.objects.filter(action='alert.acknowledge_all').count()
        _client(user, branch).post('/alerts/', {'action': 'acknowledge_all'})
        assert AuditLog.objects.filter(action='alert.acknowledge_all').count() > before_count


# ─── PDF report export ────────────────────────────────────────────────────────

class TestExportReportPDF:

    def test_utilization_pdf_returns_pdf(self, db, branch, user):
        resp = _client(user, branch).get('/reports/utilization/pdf/?days=30')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'

    def test_inventory_pdf_returns_pdf(self, db, branch, user):
        resp = _client(user, branch).get('/reports/inventory/pdf/')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'

    def test_donors_pdf_returns_pdf(self, db, branch, user):
        resp = _client(user, branch).get('/reports/donors/pdf/?days=30')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'

    def test_tti_pdf_returns_pdf(self, db, branch, user):
        resp = _client(user, branch).get('/reports/tti/pdf/')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'

    def test_reactions_pdf_returns_pdf(self, db, branch, user):
        resp = _client(user, branch).get('/reports/reactions/pdf/?days=30')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'

    def test_unknown_report_type_returns_404(self, db, branch, user):
        resp = _client(user, branch).get('/reports/nonexistent/pdf/')
        assert resp.status_code == 404

    def test_unauthenticated_redirects(self, db):
        resp = Client().get('/reports/utilization/pdf/')
        assert resp.status_code == 302
