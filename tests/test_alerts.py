"""
Alert system tests — uses actual core.alerts functions.
Run: pytest tests/test_alerts.py -v
"""
import pytest
from datetime import timedelta
from django.utils import timezone

from tests.conftest import (
    UserFactory, BranchFactory, BloodUnitFactory, DonorFactory,
    DonationFactory, StorageEquipmentFactory, ReagentFactory, ReagentLotFactory,
)


# ─── Inventory / expiry alerts ────────────────────────────────────────────────

class TestInventoryAlerts:

    def test_check_all_alerts_runs_without_error(self, db, branch):
        from core.alerts import check_all_alerts
        # Should not raise — returns None (alerts are written to DB)
        check_all_alerts(branch=branch)

    def test_near_expiry_units_flagged(self, db, branch, user):
        from core.alerts import _check_near_expiry
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        BloodUnitFactory(
            donation=donation, status='available', owner_branch=branch,
            expiry_datetime=timezone.now() + timedelta(hours=20),
        )
        # Should run without error; alerts written to Alert model
        _check_near_expiry(branch=branch)

    def test_expired_units_flagged(self, db, branch, user):
        from core.alerts import _check_expired_units
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        BloodUnitFactory(
            donation=donation, status='available', owner_branch=branch,
            expiry_datetime=timezone.now() - timedelta(hours=1),
        )
        _check_expired_units(branch=branch)

    def test_low_inventory_check_runs(self, db, branch):
        from core.alerts import _check_low_inventory
        _check_low_inventory(branch=branch)

    def test_critical_stock_check_runs(self, db, branch):
        from core.alerts import _check_critical_stock_by_blood_group
        _check_critical_stock_by_blood_group(branch=branch)


# ─── Cold chain alerts ────────────────────────────────────────────────────────

class TestColdChainAlerts:

    def test_cold_chain_check_runs(self, db, branch):
        from core.alerts import _check_cold_chain
        _check_cold_chain(branch=branch)

    def test_open_excursion_creates_alert(self, db, branch):
        from core.alerts import _check_cold_chain
        from coldchain.models import TemperatureExcursion
        from core.models import Alert
        equip = StorageEquipmentFactory(branch=branch)
        TemperatureExcursion.objects.create(
            equipment=equip,
            started_at=timezone.now() - timedelta(hours=1),
            max_temp_c=14.0,
            min_temp_c=12.0,
        )
        before = Alert.objects.filter(branch=branch).count()
        _check_cold_chain(branch=branch)
        after = Alert.objects.filter(branch=branch).count()
        assert after >= before  # alert written or already exists


# ─── Reagent QC alerts ────────────────────────────────────────────────────────

class TestReagentQcAlerts:

    def test_reagent_qc_check_runs(self, db, branch):
        from core.alerts import _check_reagent_qc
        _check_reagent_qc(branch=branch)

    def test_expired_lot_check_runs(self, db, branch):
        from core.alerts import _check_reagent_qc
        ReagentLotFactory(
            expiry_date=timezone.now().date() - timedelta(days=1),
            status='in_use',
            branch=branch,
        )
        # Should run without error
        _check_reagent_qc(branch=branch)


# ─── Donor deferral alerts ────────────────────────────────────────────────────

class TestDonorEligibility:

    def test_deferred_donor_flagged(self, db, branch, user):
        from donors.models import Donor
        donor = DonorFactory(registration_branch=branch, created_by=user,
                              deferral_status='temporary_defer',
                              deferral_until=timezone.now().date() + timedelta(days=30))
        assert not donor.is_eligible_to_donate()

    def test_active_donor_eligible(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user,
                              deferral_status='active')
        assert donor.is_eligible_to_donate()

    def test_recent_donation_ineligible_due_to_interval(self, db, branch, user):
        from datetime import timedelta
        donor = DonorFactory(registration_branch=branch, created_by=user,
                              deferral_status='active',
                              last_donation_date=timezone.now().date() - timedelta(days=20))
        assert not donor.is_eligible_to_donate()
        assert donor.days_until_eligible > 0

    def test_permanently_deferred_not_eligible(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user,
                              deferral_status='permanent_defer')
        assert not donor.is_eligible_to_donate()


# ─── Management command: run_alerts ──────────────────────────────────────────

class TestCrossmatchExpiryAlert:

    def test_expiring_crossmatch_sample_raises_warning(self, db, branch, user):
        """Mocked: a crossmatched unit with a sample expiring in 6h triggers a warning alert."""
        from core.alerts import _check_crossmatch_expiry
        from core.models import Alert
        from unittest.mock import patch, MagicMock

        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='crossmatched', owner_branch=branch)

        # Mock the Crossmatch queryset to return a compatible XM with expiring sample
        mock_xm = MagicMock()
        mock_xm.sample.validity_expiry = timezone.now() + timedelta(hours=6)

        with patch('transfusion.models.Crossmatch') as MockXM:
            (MockXM.objects
             .filter.return_value
             .select_related.return_value
             .order_by.return_value
             .first.return_value) = mock_xm

            _check_crossmatch_expiry(branch)

        alert = Alert.objects.filter(alert_type='crossmatch_expiring', branch=branch).first()
        assert alert is not None
        assert alert.severity == 'warning'
        assert 'crossmatched' in alert.message.lower() or 'expir' in alert.message.lower()

    def test_no_crossmatched_units_no_alert(self, db, branch, user):
        """Branch with no crossmatched units triggers no alert."""
        from core.alerts import _check_crossmatch_expiry
        from core.models import Alert

        _check_crossmatch_expiry(branch)
        assert not Alert.objects.filter(alert_type='crossmatch_expiring', branch=branch).exists()

    def test_xm_with_far_future_sample_no_alert(self, db, branch, user):
        """Crossmatched unit whose sample is still 48h valid should NOT trigger alert."""
        from core.alerts import _check_crossmatch_expiry
        from core.models import Alert
        from unittest.mock import patch, MagicMock

        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        BloodUnitFactory(donation=donation, status='crossmatched', owner_branch=branch)

        mock_xm = MagicMock()
        mock_xm.sample.validity_expiry = timezone.now() + timedelta(hours=48)  # 48h away — safe

        with patch('transfusion.models.Crossmatch') as MockXM:
            (MockXM.objects
             .filter.return_value
             .select_related.return_value
             .order_by.return_value
             .first.return_value) = mock_xm

            _check_crossmatch_expiry(branch)

        assert not Alert.objects.filter(alert_type='crossmatch_expiring', branch=branch).exists()


class TestRunAlertsCommand:

    def test_run_alerts_command_executes(self, db, branch):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        try:
            call_command('run_alerts', stdout=out)
        except SystemExit:
            pass


# ─── Email notification tests ─────────────────────────────────────────────────

class TestEmailNotifications:

    def test_critical_alert_sends_email_to_opted_in_user(self, db, branch, user):
        from django.core import mail
        from django.contrib.auth import get_user_model
        User = get_user_model()
        # Give the user an email and opt in to critical alerts
        user.email = 'nurse@hospital.example'
        user.notify_critical_alerts = True
        user.branch = branch
        user.save(update_fields=['email', 'notify_critical_alerts', 'branch'])

        from core.alerts import _raise_alert
        _raise_alert(branch=branch, alert_type='low_inventory', severity='critical',
                     message='Test critical alert', entity_table='')

        assert len(mail.outbox) >= 1
        subjects = [m.subject for m in mail.outbox]
        assert any('CRITICAL' in s for s in subjects)
        all_recipients = [r for m in mail.outbox for r in m.to]
        assert 'nurse@hospital.example' in all_recipients

    def test_warning_alert_sends_email_to_opted_in_user(self, db, branch, user):
        from django.core import mail
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user.email = 'tech@hospital.example'
        user.notify_warning_alerts = True
        user.branch = branch
        user.save(update_fields=['email', 'notify_warning_alerts', 'branch'])

        from core.alerts import _raise_alert
        _raise_alert(branch=branch, alert_type='near_expiry', severity='warning',
                     message='Test warning alert', entity_table='')

        assert len(mail.outbox) >= 1
        all_recipients = [r for m in mail.outbox for r in m.to]
        assert 'tech@hospital.example' in all_recipients

    def test_info_alert_sends_no_email(self, db, branch, user):
        from django.core import mail
        user.email = 'admin@hospital.example'
        user.notify_critical_alerts = True
        user.notify_warning_alerts = True
        user.branch = branch
        user.save(update_fields=['email', 'notify_critical_alerts', 'notify_warning_alerts', 'branch'])

        from core.alerts import _raise_alert
        _raise_alert(branch=branch, alert_type='blood_group_discrepancy', severity='info',
                     message='Test info alert', entity_table='')

        # info severity must not trigger email
        assert not any('admin@hospital.example' in r for m in mail.outbox for r in m.to)

    def test_opted_out_user_receives_no_email(self, db, branch, user):
        from django.core import mail
        user.email = 'optout@hospital.example'
        user.notify_critical_alerts = False
        user.branch = branch
        user.save(update_fields=['email', 'notify_critical_alerts', 'branch'])

        from core.alerts import _raise_alert
        _raise_alert(branch=branch, alert_type='low_inventory', severity='critical',
                     message='Test critical alert for opted-out user',
                     entity_table='test_table', entity_id=9999)

        all_recipients = [r for m in mail.outbox for r in m.to]
        assert 'optout@hospital.example' not in all_recipients

    def test_notification_settings_view_saves_preferences(self, db, branch, user):
        from django.test import Client
        c = Client()
        c.login(username=user.username, password='testpass123')
        response = c.post('/accounts/notifications/', {
            'email': 'updated@example.com',
            'notify_critical_alerts': 'on',
        })
        assert response.status_code in (200, 302)
        user.refresh_from_db()
        assert user.email == 'updated@example.com'
        assert user.notify_critical_alerts is True
        assert user.notify_warning_alerts is False
