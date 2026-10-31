"""
Tests for the lookback system — safety-critical WHO/SHOT compliance feature.

A lookback campaign is initiated when a repeat donor tests reactive for a TTI
(HIV, HCV, HBV, etc.). All previous donations in the window period are traced
and recipients notified via their treating clinician.
"""
import pytest
import hashlib
from datetime import timedelta
from django.utils import timezone
from django.test import Client

from tests.conftest import (
    UserFactory, BranchFactory, DonorFactory, DonationFactory,
    BloodUnitFactory, PatientFactory, BloodRequestFactory,
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
        username=f'su_lb_{branch.pk}_{timezone.now().timestamp():.0f}',
        password='testpass123',
        display_name='LB Super',
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
        signed_payload_hash=hashlib.sha256(b'lookback-test').hexdigest(),
        manifested_name=user.display_name or user.username,
    )


def _make_reactive_test_result(branch, donor, user):
    """Create a DonationTestResult with result='reactive' for lookback initiation."""
    from transfusion.models import TestDefinition, DonationTestResult, Sample

    test_def, _ = TestDefinition.objects.get_or_create(
        test_code='HIV-1/2-ELISA',
        defaults={
            'name': 'HIV 1/2 Antibody ELISA',
            'pathogen': 'HIV',
            'method': 'ELISA',
            'mandatory': True,
            'applies_to': 'donors',
        },
    )
    donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
    donor_sample = Sample.objects.create(
        donor=donor,
        collected_by=user,
        sample_type='donor_screening',
        accession_number=f'DS-{donation.pk}-{timezone.now().timestamp():.0f}',
        collected_at=timezone.now() - timedelta(hours=2),
        branch=branch,
    )
    reviewer = _su(branch)
    result = DonationTestResult.objects.create(
        donation=donation,
        test=test_def,
        sample=donor_sample,
        result='reactive',
        performed_by=user,
        reviewed_by=reviewer,
        esign=_make_esign(user),
        performed_at=timezone.now(),
    )
    return result, donation


# ─── Lookback list ────────────────────────────────────────────────────────────

class TestLookbackList:

    def test_lookback_list_get_empty(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/lookback/')
        assert resp.status_code == 200

    def test_lookback_list_shows_campaigns(self, db, branch, user):
        from transfusion.models import LookbackCampaign
        donor = DonorFactory(registration_branch=branch, created_by=user)
        LookbackCampaign.objects.create(
            donor=donor,
            triggered_by_test='HIV-1/2',
            triggered_at=timezone.now(),
            initiated_by=user,
            lookback_from=timezone.now().date() - timedelta(days=90),
            status='open',
        )
        resp = _client(user, branch).get('/transfusion/lookback/')
        assert resp.status_code == 200
        assert len(resp.context['campaigns']) == 1


# ─── Lookback initiate ────────────────────────────────────────────────────────

class TestLookbackInitiate:

    def test_lookback_initiate_get(self, db, branch, user):
        resp = _client(user, branch).get('/transfusion/lookback/initiate/')
        assert resp.status_code == 200

    def test_lookback_initiate_post_creates_campaign(self, db, branch, user):
        from transfusion.models import LookbackCampaign
        donor = DonorFactory(registration_branch=branch, created_by=user)
        reactive_result, _ = _make_reactive_test_result(branch, donor, user)
        resp = _client(user, branch).post('/transfusion/lookback/initiate/', {
            'test_result_pk': reactive_result.pk,
        })
        assert resp.status_code in (200, 302)
        assert LookbackCampaign.objects.filter(donor=donor).exists()

    def test_lookback_initiate_invalid_pk_redirects(self, db, branch, user):
        resp = _client(user, branch).post('/transfusion/lookback/initiate/', {
            'test_result_pk': '999999',
        })
        assert resp.status_code in (200, 302)
        from transfusion.models import LookbackCampaign
        assert LookbackCampaign.objects.count() == 0

    def test_lookback_initiate_non_reactive_result_rejected(self, db, branch, user):
        """A non-reactive result cannot trigger a lookback campaign."""
        from transfusion.models import TestDefinition, DonationTestResult, Sample, LookbackCampaign
        test_def, _ = TestDefinition.objects.get_or_create(
            test_code='HCV-NAT',
            defaults={'name': 'HCV NAT', 'pathogen': 'HCV', 'method': 'NAT',
                      'mandatory': True, 'applies_to': 'donors'},
        )
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        sample = Sample.objects.create(
            donor=donor, collected_by=user, sample_type='donor_screening',
            accession_number=f'NRDS-{donation.pk}', collected_at=timezone.now(),
            branch=branch,
        )
        reviewer = _su(branch)
        non_reactive = DonationTestResult.objects.create(
            donation=donation, test=test_def, sample=sample,
            result='non_reactive', performed_by=user, reviewed_by=reviewer,
            esign=_make_esign(user), performed_at=timezone.now(),
        )
        resp = _client(user, branch).post('/transfusion/lookback/initiate/', {
            'test_result_pk': non_reactive.pk,
        })
        assert LookbackCampaign.objects.count() == 0

    def test_lookback_initiate_identifies_recipients(self, db, branch, user):
        """Prior transfused units from same donor should create notifications."""
        from transfusion.models import (
            LookbackCampaign, LookbackNotification, IssueTransaction
        )
        from audit.models import ElectronicSignature
        donor = DonorFactory(registration_branch=branch, created_by=user)

        # Prior donation 30 days ago with a transfused unit
        old_donation = DonationFactory(
            donor=donor, branch=branch, collected_by=user,
            donated_at=timezone.now() - timedelta(days=30),
        )
        old_unit = BloodUnitFactory(
            donation=old_donation, status='transfused', owner_branch=branch,
        )
        patient = PatientFactory(created_by=user)
        blood_request = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        esign = _make_esign(user)
        IssueTransaction.objects.create(
            blood_unit=old_unit, request=blood_request, patient=patient,
            issued_by=user, issue_esign=esign, abo_check_passed=True,
            issued_at=timezone.now() - timedelta(days=30),
            intended_branch=branch,
        )

        # Reactive result on current donation
        reactive_result, _ = _make_reactive_test_result(branch, donor, user)

        _client(user, branch).post('/transfusion/lookback/initiate/', {
            'test_result_pk': reactive_result.pk,
        })

        campaign = LookbackCampaign.objects.filter(donor=donor).first()
        assert campaign is not None
        assert LookbackNotification.objects.filter(campaign=campaign).count() == 1


# ─── Lookback detail ──────────────────────────────────────────────────────────

class TestLookbackDetail:

    def _make_campaign(self, branch, user):
        from transfusion.models import LookbackCampaign
        donor = DonorFactory(registration_branch=branch, created_by=user)
        return LookbackCampaign.objects.create(
            donor=donor,
            triggered_by_test='HIV-1/2',
            triggered_at=timezone.now(),
            initiated_by=user,
            lookback_from=timezone.now().date() - timedelta(days=45),
            status='open',
        )

    def test_lookback_detail_get(self, db, branch, user):
        campaign = self._make_campaign(branch, user)
        resp = _client(user, branch).get(f'/transfusion/lookback/{campaign.pk}/')
        assert resp.status_code == 200

    def test_lookback_detail_shows_pending_count(self, db, branch, user):
        campaign = self._make_campaign(branch, user)
        resp = _client(user, branch).get(f'/transfusion/lookback/{campaign.pk}/')
        assert resp.context['pending_count'] == 0

    def test_lookback_detail_close_campaign(self, db, branch, user):
        campaign = self._make_campaign(branch, user)
        resp = _client(user, branch).post(f'/transfusion/lookback/{campaign.pk}/', {
            'action': 'close',
        })
        assert resp.status_code in (200, 302)
        campaign.refresh_from_db()
        assert campaign.status == 'closed'
        assert campaign.closed_by == user


# ─── Update notification ──────────────────────────────────────────────────────

class TestUpdateNotification:

    def _make_campaign_with_notification(self, branch, user):
        from transfusion.models import LookbackCampaign, LookbackNotification, IssueTransaction
        donor = DonorFactory(registration_branch=branch, created_by=user)
        campaign = LookbackCampaign.objects.create(
            donor=donor, triggered_by_test='HCV-Ab',
            triggered_at=timezone.now(), initiated_by=user,
            lookback_from=timezone.now().date() - timedelta(days=70), status='open',
        )
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='transfused', owner_branch=branch)
        patient = PatientFactory(created_by=user)
        blood_request = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)
        esign = _make_esign(user)
        tx = IssueTransaction.objects.create(
            blood_unit=unit, request=blood_request, patient=patient,
            issued_by=user, issue_esign=esign, abo_check_passed=True,
            issued_at=timezone.now() - timedelta(days=65), intended_branch=branch,
        )
        notif = LookbackNotification.objects.create(
            campaign=campaign, patient=patient, issue_tx=tx,
            unit_did=unit.did,
            transfusion_date=(timezone.now() - timedelta(days=65)).date(),
            status='pending',
        )
        return campaign, notif

    def test_update_notification_get(self, db, branch, user):
        campaign, notif = self._make_campaign_with_notification(branch, user)
        resp = _client(user, branch).get(
            f'/transfusion/lookback/{campaign.pk}/notify/{notif.pk}/'
        )
        assert resp.status_code in (200, 302)

    def test_update_notification_mark_notified(self, db, branch, user):
        campaign, notif = self._make_campaign_with_notification(branch, user)
        resp = _client(user, branch).post(
            f'/transfusion/lookback/{campaign.pk}/notify/{notif.pk}/', {
                'status': 'notified',
                'clinician_name': 'Dr A Smith',
                'notes': 'GP contacted by phone. Patient recalled for HCV testing.',
            }
        )
        assert resp.status_code in (200, 302)
        notif.refresh_from_db()
        assert notif.status == 'notified'
        assert notif.notified_by == user
        assert notif.clinician_name == 'Dr A Smith'

    def test_update_notification_not_reachable(self, db, branch, user):
        campaign, notif = self._make_campaign_with_notification(branch, user)
        resp = _client(user, branch).post(
            f'/transfusion/lookback/{campaign.pk}/notify/{notif.pk}/', {
                'status': 'not_reachable',
                'notes': 'Patient phone disconnected. GP informed.',
            }
        )
        notif.refresh_from_db()
        assert notif.status == 'not_reachable'

    def test_all_notified_auto_updates_campaign(self, db, branch, user):
        """When all notifications are notified, campaign status should auto-update."""
        campaign, notif = self._make_campaign_with_notification(branch, user)
        _client(user, branch).post(
            f'/transfusion/lookback/{campaign.pk}/notify/{notif.pk}/', {
                'status': 'notified',
                'clinician_name': 'Dr B Jones',
                'notes': 'Notified.',
            }
        )
        campaign.refresh_from_db()
        assert campaign.status == 'notified'
