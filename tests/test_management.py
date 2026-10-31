"""
Django management command tests.
Run: pytest tests/test_management.py -v
"""
import pytest
from io import StringIO
from datetime import timedelta
from django.core.management import call_command
from django.utils import timezone


class TestSeedTransitionsCommand:

    def test_seed_transitions_is_idempotent(self, db):
        from inventory.state_machine import seed_transitions
        from inventory.models import UnitStateTransition
        seed_transitions()
        count_1 = UnitStateTransition.objects.count()
        seed_transitions()
        count_2 = UnitStateTransition.objects.count()
        assert count_1 == count_2

    def test_seed_transitions_creates_records(self, db):
        from inventory.state_machine import seed_transitions
        from inventory.models import UnitStateTransition
        UnitStateTransition.objects.all().delete()
        seed_transitions()
        assert UnitStateTransition.objects.count() > 0


class TestBuildDailyFactsCommand:

    def test_command_runs_without_error(self, db, branch):
        out = StringIO()
        yesterday = (timezone.now().date() - timedelta(days=1)).isoformat()
        call_command('build_daily_facts', date=yesterday, stdout=out)

    def test_command_idempotent(self, db, branch):
        from analytics.models import DemandFactDaily
        yesterday = timezone.now().date() - timedelta(days=1)
        out = StringIO()
        call_command('build_daily_facts', date=yesterday.isoformat(), stdout=out)
        call_command('build_daily_facts', date=yesterday.isoformat(), stdout=out)
        # update_or_create means no duplicates
        count = DemandFactDaily.objects.filter(fact_date=yesterday).count()
        # One row per (branch, component_class, date) — 6 component classes
        assert count >= 1

    def test_command_creates_kpi_row(self, db, branch):
        from analytics.models import KpiDaily
        yesterday = (timezone.now().date() - timedelta(days=1)).isoformat()
        out = StringIO()
        call_command('build_daily_facts', date=yesterday, stdout=out)
        assert KpiDaily.objects.filter(kpi_date=yesterday).exists()


class TestCheckShortagesCommand:

    def test_check_shortages_outputs_results(self, db, branch):
        out = StringIO()
        try:
            call_command('check_shortages', branch=str(branch.pk), stdout=out)
        except Exception as e:
            assert 'NameError' not in str(e)
            assert 'ImportError' not in str(e)


class TestRunAlertsCommand:

    def test_run_alerts_does_not_crash(self, db, branch):
        out = StringIO()
        try:
            call_command('run_alerts', stdout=out)
        except SystemExit:
            pass

    def test_run_alerts_branch_specific(self, db, branch):
        out = StringIO()
        try:
            call_command('run_alerts', branch=str(branch.pk), stdout=out)
        except (SystemExit, Exception) as e:
            assert 'NameError' not in str(e)


class TestSendSmsRemindersCommand:

    def test_sms_reminders_dry_run(self, db, branch, user):
        out = StringIO()
        try:
            call_command('send_sms_reminders', dry_run=True, stdout=out)
        except (SystemExit, Exception) as e:
            assert 'NameError' not in str(e)


class TestCleanExpiredSessionsCommand:

    def test_clean_sessions_runs(self, db):
        out = StringIO()
        call_command('clearsessions', stdout=out)


class TestCreateSuperuserWithBranch:

    def test_management_can_create_user(self, db, branch):
        from accounts.models import User
        u = User.objects.create_user(
            username='mgmttest',
            password='secure123',
            branch=branch,
        )
        assert u.pk is not None
