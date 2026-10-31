"""
Donor retention campaign tests — email dispatch, template rendering, status tracking.
Run: pytest tests/test_campaigns.py -v
"""
import pytest
from datetime import timedelta
from django.utils import timezone
from django.core import mail
from django.core.management import call_command
from io import StringIO

from tests.conftest import UserFactory, BranchFactory, DonorFactory


def _make_donor_with_email(branch, user, email_address):
    """Create a Donor whose encrypted contact field contains an email address."""
    from privacy.models import SubjectIdentity
    subject = SubjectIdentity.create_from_plain(
        name='Test Donor',
        national_id='',
        contact=email_address,
        subject_type='donor',
        created_by=user,
    )
    donor = DonorFactory(
        subject=subject,
        registration_branch=branch,
        created_by=user,
        last_donation_date=timezone.now().date(),
    )
    return donor


def _make_campaign(branch, user, channel='email', status='active'):
    from donors.models import RetentionCampaign
    return RetentionCampaign.objects.create(
        name='Test Re-engagement Campaign',
        branch=branch,
        segment='lapsed_6m',
        channel=channel,
        message_template=(
            'Dear {name}, we miss you! Your last donation was on {last_donation}. '
            'Please come back and donate again.'
        ),
        goal_donations=10,
        status=status,
        created_by=user,
    )


def _enroll(campaign, donor):
    from donors.models import CampaignEnrollment
    return CampaignEnrollment.objects.create(campaign=campaign, donor=donor)


# ─── Email extraction helper ───────────────────────────────────────────────────

class TestExtractEmail:

    def test_extracts_simple_email(self):
        from donors.management.commands.send_campaign_emails import _extract_email
        assert _extract_email('john@example.com') == 'john@example.com'

    def test_extracts_email_from_mixed_text(self):
        from donors.management.commands.send_campaign_emails import _extract_email
        assert _extract_email('+44 7700 900123 / nurse@hospital.org') == 'nurse@hospital.org'

    def test_returns_none_for_phone_only(self):
        from donors.management.commands.send_campaign_emails import _extract_email
        assert _extract_email('+44 7700 900123') is None

    def test_returns_none_for_empty(self):
        from donors.management.commands.send_campaign_emails import _extract_email
        assert _extract_email('') is None
        assert _extract_email(None) is None


# ─── Template rendering ────────────────────────────────────────────────────────

class TestTemplateRendering:

    def test_renders_name_and_date(self):
        from donors.management.commands.send_campaign_emails import _render_template
        import datetime
        body = _render_template(
            'Hello {name}, last gave on {last_donation}.',
            name='Alice',
            last_donation=datetime.date(2026, 1, 15),
        )
        assert 'Alice' in body
        assert '15 Jan 2026' in body

    def test_renders_no_donation_date(self):
        from donors.management.commands.send_campaign_emails import _render_template
        body = _render_template('Hi {name}, last: {last_donation}.', name='Bob', last_donation=None)
        assert 'Bob' in body
        assert 'a while ago' in body


# ─── Management command ────────────────────────────────────────────────────────

class TestSendCampaignEmails:

    def test_sends_email_to_enrolled_donor(self, db, branch, user):
        donor = _make_donor_with_email(branch, user, 'donor@example.com')
        campaign = _make_campaign(branch, user, channel='email', status='active')
        _enroll(campaign, donor)

        out = StringIO()
        call_command('send_campaign_emails', stdout=out)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['donor@example.com']
        assert campaign.name in mail.outbox[0].subject

    def test_enrollment_status_updated_to_contacted(self, db, branch, user):
        from donors.models import CampaignEnrollment
        donor = _make_donor_with_email(branch, user, 'donor2@example.com')
        campaign = _make_campaign(branch, user)
        enroll = _enroll(campaign, donor)

        call_command('send_campaign_emails', stdout=StringIO())

        enroll.refresh_from_db()
        assert enroll.status == 'contacted'
        assert enroll.contacted_at is not None

    def test_donor_without_email_skipped(self, db, branch, user):
        from privacy.models import SubjectIdentity
        subject = SubjectIdentity.create_from_plain(
            name='Phone Only', national_id='', contact='+44 7700 900000',
            subject_type='donor', created_by=user,
        )
        donor = DonorFactory(subject=subject, registration_branch=branch, created_by=user)
        campaign = _make_campaign(branch, user)
        enroll = _enroll(campaign, donor)

        call_command('send_campaign_emails', stdout=StringIO())

        assert len(mail.outbox) == 0
        enroll.refresh_from_db()
        assert enroll.status == 'enrolled'  # unchanged

    def test_dry_run_does_not_send(self, db, branch, user):
        donor = _make_donor_with_email(branch, user, 'dryrun@example.com')
        campaign = _make_campaign(branch, user)
        enroll = _enroll(campaign, donor)

        call_command('send_campaign_emails', '--dry-run', stdout=StringIO())

        assert len(mail.outbox) == 0
        enroll.refresh_from_db()
        assert enroll.status == 'enrolled'  # not updated in dry run

    def test_inactive_campaign_not_processed(self, db, branch, user):
        donor = _make_donor_with_email(branch, user, 'inactive@example.com')
        campaign = _make_campaign(branch, user, status='draft')
        _enroll(campaign, donor)

        call_command('send_campaign_emails', stdout=StringIO())

        assert len(mail.outbox) == 0

    def test_mixed_channel_campaign_processed(self, db, branch, user):
        donor = _make_donor_with_email(branch, user, 'mixed@example.com')
        campaign = _make_campaign(branch, user, channel='mixed')
        _enroll(campaign, donor)

        call_command('send_campaign_emails', stdout=StringIO())

        assert len(mail.outbox) == 1

    def test_already_contacted_enrollment_skipped(self, db, branch, user):
        from donors.models import CampaignEnrollment
        donor = _make_donor_with_email(branch, user, 'already@example.com')
        campaign = _make_campaign(branch, user)
        CampaignEnrollment.objects.create(
            campaign=campaign, donor=donor,
            status='contacted', contacted_at=timezone.now(),
        )

        call_command('send_campaign_emails', stdout=StringIO())

        assert len(mail.outbox) == 0

    def test_limit_caps_sends(self, db, branch, user):
        campaign = _make_campaign(branch, user)
        for i in range(5):
            d = _make_donor_with_email(branch, user, f'donor{i}@example.com')
            _enroll(campaign, d)

        call_command('send_campaign_emails', '--limit', '2', stdout=StringIO())

        assert len(mail.outbox) == 2

    def test_sms_channel_campaign_not_processed(self, db, branch, user):
        donor = _make_donor_with_email(branch, user, 'sms@example.com')
        campaign = _make_campaign(branch, user, channel='sms')
        _enroll(campaign, donor)

        call_command('send_campaign_emails', stdout=StringIO())

        assert len(mail.outbox) == 0

    def test_campaign_filter_by_pk(self, db, branch, user):
        donor_a = _make_donor_with_email(branch, user, 'camp_a@example.com')
        donor_b = _make_donor_with_email(branch, user, 'camp_b@example.com')
        campaign_a = _make_campaign(branch, user)
        campaign_b = _make_campaign(branch, user)
        _enroll(campaign_a, donor_a)
        _enroll(campaign_b, donor_b)

        call_command('send_campaign_emails', '--campaign', str(campaign_a.pk), stdout=StringIO())

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['camp_a@example.com']


# ─── Deferral recall emails ────────────────────────────────────────────────────

class TestDeferralRecallEmails:

    def test_recall_email_sent_when_deferral_expires(self, db, branch, user):
        """donor_engagement --send-recall-emails emails donors whose deferral just expired."""
        from privacy.models import SubjectIdentity
        subject = SubjectIdentity.create_from_plain(
            name='Jane Donor', national_id='', contact='jane@example.com',
            subject_type='donor', created_by=user,
        )
        donor = DonorFactory(
            subject=subject,
            registration_branch=branch,
            created_by=user,
            deferral_status='temporary_defer',
            deferral_until=timezone.now().date() - timedelta(days=1),  # expired yesterday
        )

        out = StringIO()
        call_command('donor_engagement', '--send-recall-emails', stdout=out)

        assert len(mail.outbox) >= 1
        all_recipients = [r for m in mail.outbox for r in m.to]
        assert 'jane@example.com' in all_recipients
        # Donor status should be cleared
        donor.refresh_from_db()
        assert donor.deferral_status == 'active'

    def test_no_recall_email_without_flag(self, db, branch, user):
        """Without --send-recall-emails, no email is sent even if deferral expires."""
        from privacy.models import SubjectIdentity
        subject = SubjectIdentity.create_from_plain(
            name='Bob Donor', national_id='', contact='bob@example.com',
            subject_type='donor', created_by=user,
        )
        DonorFactory(
            subject=subject,
            registration_branch=branch,
            created_by=user,
            deferral_status='temporary_defer',
            deferral_until=timezone.now().date() - timedelta(days=1),
        )

        call_command('donor_engagement', stdout=StringIO())

        assert not any('bob@example.com' in r for m in mail.outbox for r in m.to)

    def test_donor_without_email_not_emailed(self, db, branch, user):
        """Donors whose contact_enc holds only a phone number are skipped gracefully."""
        from privacy.models import SubjectIdentity
        subject = SubjectIdentity.create_from_plain(
            name='Phone Guy', national_id='', contact='+44 7700 000001',
            subject_type='donor', created_by=user,
        )
        DonorFactory(
            subject=subject,
            registration_branch=branch,
            created_by=user,
            deferral_status='temporary_defer',
            deferral_until=timezone.now().date() - timedelta(days=1),
        )

        out = StringIO()
        call_command('donor_engagement', '--send-recall-emails', stdout=out)

        # No error raised, just no email
        assert len(mail.outbox) == 0

    def test_still_deferred_donor_not_emailed(self, db, branch, user):
        """Donor whose deferral_until is still in the future should not receive recall email."""
        from privacy.models import SubjectIdentity
        subject = SubjectIdentity.create_from_plain(
            name='Still Deferred', national_id='', contact='deferred@example.com',
            subject_type='donor', created_by=user,
        )
        DonorFactory(
            subject=subject,
            registration_branch=branch,
            created_by=user,
            deferral_status='temporary_defer',
            deferral_until=timezone.now().date() + timedelta(days=30),  # future
        )

        call_command('donor_engagement', '--send-recall-emails', stdout=StringIO())

        all_recipients = [r for m in mail.outbox for r in m.to]
        assert 'deferred@example.com' not in all_recipients
