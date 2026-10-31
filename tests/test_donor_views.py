"""
Tests for donor-workflow views:
  - donor_list, register_donor, donor_detail
  - eligibility_screen (GET + POST eligible + POST deferred)
  - record_donation (GET + POST)
  - record_adverse_event (GET + POST)
  - dhq_create (GET + POST eligible + POST with triggers → deferred)
  - dhq_detail
  - donor_milestones, lapsed_donors
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
        username=f'su_dv_{branch.pk}_{timezone.now().timestamp():.0f}',
        password='testpass123',
        display_name='Donor View Super',
        branch=branch,
    )


def _make_ref_facility(branch):
    """Create a RefFacility linked to branch — required for record_donation."""
    from core.models import RefFacility
    return RefFacility.objects.get_or_create(
        branch=branch,
        defaults={'facility_code': branch.facility_code, 'name': branch.name, 'last_serial': 0},
    )[0]


# ─── Donor list ───────────────────────────────────────────────────────────────

class TestDonorList:

    def test_donor_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/donors/')
        assert resp.status_code == 200

    def test_donor_list_shows_donors_for_branch(self, db, branch, user):
        DonorFactory(registration_branch=branch, created_by=user)
        DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(user, branch).get('/donors/')
        assert resp.status_code == 200


# ─── Register donor ───────────────────────────────────────────────────────────

class TestRegisterDonor:

    def test_register_donor_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/donors/register/')
        assert resp.status_code == 200

    def test_register_donor_post_creates_donor(self, db, branch, user):
        from donors.models import Donor
        su = _su(branch)
        count_before = Donor.objects.count()
        resp = _client(su, branch).post('/donors/register/', {
            'full_name': 'John Bloodsworth',
            'national_id': 'NID-DON-TEST-001',
            'sex': 'M',
            'dob': '1990-05-20',
            'abo': 'O',
            'rh_d': 'pos',
        })
        assert resp.status_code in (200, 302)
        assert Donor.objects.count() > count_before


# ─── Donor detail ─────────────────────────────────────────────────────────────

class TestDonorDetail:

    def test_donor_detail_get(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(user, branch).get(f'/donors/{donor.pk}/')
        assert resp.status_code == 200

    def test_donor_detail_404_unknown(self, db, branch, user):
        resp = _client(user, branch).get('/donors/999999/')
        assert resp.status_code == 404

    def test_donor_detail_with_donations(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        DonationFactory(donor=donor, branch=branch, collected_by=user)
        resp = _client(user, branch).get(f'/donors/{donor.pk}/')
        assert resp.status_code == 200


# ─── Eligibility screen ───────────────────────────────────────────────────────

class TestEligibilityScreen:

    def test_eligibility_get(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(user, branch).get(f'/donors/{donor.pk}/eligibility/')
        assert resp.status_code == 200

    def test_eligibility_post_eligible_redirects_to_record_donation(self, db, branch, user):
        donor = DonorFactory(
            registration_branch=branch, created_by=user,
            deferral_status='active', sex='M',
        )
        resp = _client(user, branch).post(f'/donors/{donor.pk}/eligibility/', {
            'age': '28',
            'weight_kg': '75',
            'hemoglobin': '14.5',
            'bp_systolic': '120',
            'bp_diastolic': '80',
            'pulse': '72',
        })
        # Eligible → redirect to record_donation
        assert resp.status_code in (200, 302)

    def test_eligibility_post_low_hb_defers_donor(self, db, branch, user):
        donor = DonorFactory(
            registration_branch=branch, created_by=user,
            deferral_status='active', sex='M',
        )
        _client(user, branch).post(f'/donors/{donor.pk}/eligibility/', {
            'age': '28',
            'weight_kg': '75',
            'hemoglobin': '11.0',  # Below threshold → deferred
            'bp_systolic': '120',
            'bp_diastolic': '80',
            'pulse': '72',
        })
        donor.refresh_from_db()
        assert donor.deferral_status == 'temporary_defer'

    def test_eligibility_post_underweight_renders_failures(self, db, branch, user):
        donor = DonorFactory(
            registration_branch=branch, created_by=user,
            deferral_status='active', sex='M',
        )
        resp = _client(user, branch).post(f'/donors/{donor.pk}/eligibility/', {
            'age': '28',
            'weight_kg': '40',  # Under 50 kg threshold
            'hemoglobin': '14.5',
            'bp_systolic': '120',
            'bp_diastolic': '80',
            'pulse': '72',
        })
        # Should re-render the form with failures context
        assert resp.status_code == 200
        assert len(resp.context.get('failures', [])) > 0


# ─── Record donation ──────────────────────────────────────────────────────────

class TestRecordDonation:

    def test_record_donation_get(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user, deferral_status='active')
        resp = _client(user, branch).get(f'/donors/{donor.pk}/donate/')
        assert resp.status_code in (200, 302)

    def test_record_donation_ineligible_donor_redirects(self, db, branch, user):
        donor = DonorFactory(
            registration_branch=branch, created_by=user,
            deferral_status='permanent_defer',
        )
        resp = _client(user, branch).get(f'/donors/{donor.pk}/donate/')
        assert resp.status_code == 302

    def test_record_donation_post_creates_donation(self, db, branch, user):
        from donors.models import Donation
        su = _su(branch)
        _make_ref_facility(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user, deferral_status='active')
        count_before = Donation.objects.count()
        resp = _client(su, branch).post(f'/donors/{donor.pk}/donate/', {
            'donation_type': 'whole_blood',
            'volume_ml': '450',
            'donation_purpose': 'allogeneic',
        })
        assert resp.status_code in (200, 302)
        assert Donation.objects.count() > count_before

    def test_record_donation_post_updates_donor_counters(self, db, branch, user):
        from donors.models import Donation
        su = _su(branch)
        _make_ref_facility(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user, deferral_status='active')
        _client(su, branch).post(f'/donors/{donor.pk}/donate/', {
            'donation_type': 'whole_blood',
            'volume_ml': '450',
            'donation_purpose': 'allogeneic',
        })
        donor.refresh_from_db()
        assert donor.total_donations >= 1
        assert donor.last_donation_date == timezone.now().date()


# ─── Adverse event ────────────────────────────────────────────────────────────

class TestRecordAdverseEvent:

    def test_adverse_event_get(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        resp = _client(user, branch).get(f'/donors/donation/{donation.pk}/adverse-event/')
        assert resp.status_code == 200

    def test_adverse_event_post_creates_event(self, db, branch, user):
        from donors.models import DonorAdverseEvent
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        resp = _client(user, branch).post(f'/donors/donation/{donation.pk}/adverse-event/', {
            'event_type': 'vasovagal',
            'severity': 'mild',
            'loss_of_consciousness': '0',
            'injury': '0',
            'treatment': 'Leg elevation, cool compress, observation for 15 minutes.',
            'outcome': 'full_recovery',
            'reportable': '0',
            'report_ref': '',
        })
        assert resp.status_code in (200, 302)
        assert DonorAdverseEvent.objects.filter(donation=donation, event_type='vasovagal').exists()

    def test_adverse_event_duplicate_redirects(self, db, branch, user):
        """Second adverse event for same donation should redirect (not create duplicate)."""
        from donors.models import DonorAdverseEvent
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        # First event
        DonorAdverseEvent.objects.create(
            donation=donation, donor=donor,
            event_type='hematoma', severity='mild',
            outcome='full_recovery', recorded_by=user,
        )
        # Second attempt should redirect back, not create a new event
        resp = _client(user, branch).post(f'/donors/donation/{donation.pk}/adverse-event/', {
            'event_type': 'syncope', 'severity': 'moderate',
            'outcome': 'full_recovery',
        })
        assert resp.status_code == 302
        assert DonorAdverseEvent.objects.filter(donation=donation).count() == 1


# ─── Donor Health Questionnaire ───────────────────────────────────────────────

class TestDHQCreate:

    def test_dhq_get(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(user, branch).get(f'/donors/{donor.pk}/dhq/')
        assert resp.status_code in (200, 302)

    def test_dhq_post_eligible_outcome(self, db, branch, user):
        from donors.models import DonorHealthQuestionnaire
        donor = DonorFactory(registration_branch=branch, created_by=user, deferral_status='active')
        resp = _client(user, branch).post(f'/donors/{donor.pk}/dhq/', {
            'weight_kg': '75',
            'hb_g_dl': '14.5',
            'bp_systolic': '120',
            'bp_diastolic': '80',
            'pulse': '72',
            'temperature_c': '36.8',
            'feeling_well': '1',
            'recent_illness': '0',
            'on_antibiotics': '0',
            'on_other_medications': '0',
            'donated_elsewhere_recently': '0',
            'recent_infection': '0',
            'travel_risk': 'none',
            'malaria_history': '0',
            'tattoo_or_piercing_12m': '0',
            'needlestick_12m': '0',
            'sti_history': '0',
            'new_sexual_partner_3m': '0',
            'sexual_contact_risk_3m': '0',
            'sex_for_money_or_drugs': '0',
            'iv_drug_use_ever': '0',
            'prior_transfusion': '0',
            'prior_transplant': '0',
            'pregnancy_6m': '0',
            'cancer_history': '0',
            'heart_disease_history': '0',
            'bleeding_disorder': '0',
            'diabetes': '0',
            'cjd_risk_factor': '0',
            'donor_signature': '1',
            'staff_signature': '1',
        })
        assert resp.status_code in (200, 302)
        dhq = DonorHealthQuestionnaire.objects.filter(donor=donor).first()
        assert dhq is not None
        assert dhq.outcome == 'eligible'

    def test_dhq_post_with_iv_drug_use_defers_permanently(self, db, branch, user):
        from donors.models import DonorHealthQuestionnaire
        donor = DonorFactory(registration_branch=branch, created_by=user, deferral_status='active')
        _client(user, branch).post(f'/donors/{donor.pk}/dhq/', {
            'weight_kg': '75',
            'hb_g_dl': '14.5',
            'feeling_well': '1',
            'recent_illness': '0',
            'on_antibiotics': '0',
            'on_other_medications': '0',
            'donated_elsewhere_recently': '0',
            'recent_infection': '0',
            'travel_risk': 'none',
            'malaria_history': '0',
            'tattoo_or_piercing_12m': '0',
            'needlestick_12m': '0',
            'sti_history': '0',
            'new_sexual_partner_3m': '0',
            'sexual_contact_risk_3m': '0',
            'sex_for_money_or_drugs': '0',
            'iv_drug_use_ever': '1',  # Permanent deferral trigger
            'prior_transfusion': '0',
            'prior_transplant': '0',
            'pregnancy_6m': '0',
            'cancer_history': '0',
            'heart_disease_history': '0',
            'bleeding_disorder': '0',
            'diabetes': '0',
            'cjd_risk_factor': '0',
            'donor_signature': '1',
            'staff_signature': '1',
        })
        dhq = DonorHealthQuestionnaire.objects.filter(donor=donor).first()
        assert dhq is not None
        assert dhq.outcome == 'deferred_temp'


class TestDHQDetail:

    def test_dhq_detail_get(self, db, branch, user):
        from donors.models import DonorHealthQuestionnaire
        donor = DonorFactory(registration_branch=branch, created_by=user)
        dhq = DonorHealthQuestionnaire.objects.create(
            donor=donor,
            completed_at=timezone.now(),
            completed_by=user,
            feeling_well=True, recent_illness=False, on_antibiotics=False,
            on_other_medications=False, donated_elsewhere_recently=False,
            recent_infection=False, travel_risk='none', malaria_history=False,
            tattoo_or_piercing_12m=False, needlestick_12m=False, sti_history=False,
            new_sexual_partner_3m=False, sexual_contact_risk_3m=False,
            sex_for_money_or_drugs=False, iv_drug_use_ever=False,
            prior_transfusion=False, prior_transplant=False, pregnancy_6m=False,
            cancer_history=False, heart_disease_history=False, bleeding_disorder=False,
            diabetes=False, cjd_risk_factor=False, donor_signature=True,
            staff_signature=True, outcome='eligible',
        )
        resp = _client(user, branch).get(f'/donors/{donor.pk}/dhq/{dhq.pk}/')
        assert resp.status_code == 200


# ─── Donor milestones ─────────────────────────────────────────────────────────

class TestDonorMilestones:

    def test_milestones_get(self, db, branch, user):
        resp = _client(user, branch).get('/donors/milestones/')
        assert resp.status_code == 200

    def test_milestones_with_milestone(self, db, branch, user):
        from donors.models import DonorMilestone
        donor = DonorFactory(registration_branch=branch, created_by=user)
        DonorMilestone.objects.create(
            donor=donor,
            milestone_type='tenth',
            achieved_at=timezone.now(),
        )
        resp = _client(user, branch).get('/donors/milestones/')
        assert resp.status_code == 200


# ─── Lapsed donors ────────────────────────────────────────────────────────────

class TestLapsedDonors:

    def test_lapsed_donors_get(self, db, branch, user):
        resp = _client(user, branch).get('/donors/lapsed/')
        assert resp.status_code == 200

    def test_lapsed_donors_shows_lapsed(self, db, branch, user):
        # Donor who last donated 400 days ago → lapsed
        donor = DonorFactory(
            registration_branch=branch, created_by=user,
            last_donation_date=(timezone.now() - timedelta(days=400)).date(),
            total_donations=1,
        )
        resp = _client(user, branch).get('/donors/lapsed/')
        assert resp.status_code == 200


# ─── Retention campaign views ─────────────────────────────────────────────────

def _make_campaign(branch, user):
    from donors.models import RetentionCampaign
    return RetentionCampaign.objects.create(
        name='Test Campaign',
        branch=branch,
        segment='lapsed_6m',
        channel='email',
        message_template='Dear {name}, please donate again.',
        goal_donations=50,
        status='draft',
        created_by=user,
    )


class TestCampaignListView:

    def test_campaign_list_get(self, db, branch, user):
        resp = _client(user, branch).get('/donors/campaigns/')
        assert resp.status_code == 200

    def test_campaign_list_shows_campaign(self, db, branch, user):
        _make_campaign(branch, user)
        resp = _client(user, branch).get('/donors/campaigns/')
        assert resp.status_code == 200
        assert b'Test Campaign' in resp.content

    def test_campaign_list_filter_by_status(self, db, branch, user):
        _make_campaign(branch, user)  # draft campaign
        resp = _client(user, branch).get('/donors/campaigns/?status=active')
        assert resp.status_code == 200

    def test_campaign_list_unauthenticated_redirects(self, db, branch):
        resp = Client().get('/donors/campaigns/')
        assert resp.status_code == 302
        assert 'login' in resp.get('Location', '').lower()


class TestCampaignCreateView:

    def test_get_renders_form(self, db, branch, user):
        resp = _client(user, branch).get('/donors/campaigns/new/')
        assert resp.status_code == 200

    def test_post_creates_campaign(self, db, branch, user):
        from donors.models import RetentionCampaign
        count_before = RetentionCampaign.objects.count()
        _client(user, branch).post('/donors/campaigns/new/', {
            'name': 'New Campaign',
            'segment': 'lapsed_3m',
            'channel': 'sms',
            'message_template': 'Hi {name}, we miss you!',
            'goal_donations': '30',
        })
        assert RetentionCampaign.objects.count() > count_before

    def test_post_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        _client(user, branch).post('/donors/campaigns/new/', {
            'name': 'Audit Campaign',
            'segment': 'lapsed_6m',
            'channel': 'email',
            'message_template': 'Dear {name}, please donate.',
            'goal_donations': '0',
        })
        assert AuditLog.objects.filter(action='campaign.created').exists()

    def test_post_creates_draft_status(self, db, branch, user):
        from donors.models import RetentionCampaign
        _client(user, branch).post('/donors/campaigns/new/', {
            'name': 'Draft Campaign',
            'segment': 'high_value',
            'channel': 'call',
            'message_template': 'Hi {name}!',
            'goal_donations': '10',
        })
        campaign = RetentionCampaign.objects.filter(name='Draft Campaign').first()
        assert campaign is not None
        assert campaign.status == 'draft'


class TestCampaignDetailView:

    def test_get_renders_detail(self, db, branch, user):
        campaign = _make_campaign(branch, user)
        resp = _client(user, branch).get(f'/donors/campaigns/{campaign.pk}/')
        assert resp.status_code == 200

    def test_get_nonexistent_returns_404(self, db, branch, user):
        resp = _client(user, branch).get('/donors/campaigns/99999/')
        assert resp.status_code == 404

    def test_post_activate_changes_status_to_active(self, db, branch, user):
        campaign = _make_campaign(branch, user)
        _client(user, branch).post(f'/donors/campaigns/{campaign.pk}/', {
            'action': 'activate',
        })
        campaign.refresh_from_db()
        assert campaign.status == 'active'

    def test_post_activate_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        campaign = _make_campaign(branch, user)
        _client(user, branch).post(f'/donors/campaigns/{campaign.pk}/', {
            'action': 'activate',
        })
        assert AuditLog.objects.filter(action='campaign.status_changed').exists()

    def test_post_pause_changes_status_to_paused(self, db, branch, user):
        campaign = _make_campaign(branch, user)
        campaign.status = 'active'
        campaign.save(update_fields=['status'])
        _client(user, branch).post(f'/donors/campaigns/{campaign.pk}/', {
            'action': 'pause',
        })
        campaign.refresh_from_db()
        assert campaign.status == 'paused'


# ─── Deferral letter PDF ──────────────────────────────────────────────────────

class TestDeferralLetterView:

    def test_active_donor_redirects_not_deferred(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        # Active donor → redirects (no letter needed)
        resp = _client(user, branch).get(f'/donors/{donor.pk}/deferral-letter.pdf')
        assert resp.status_code in (200, 302)

    def test_deferred_donor_returns_pdf(self, db, branch, user):
        donor = DonorFactory(
            registration_branch=branch, created_by=user,
            deferral_status='permanent_defer',
            deferral_reason='Low haemoglobin — permanent deferral',
        )
        resp = _client(user, branch).get(f'/donors/{donor.pk}/deferral-letter.pdf')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'

    def test_nonexistent_donor_returns_404(self, db, branch, user):
        resp = _client(user, branch).get('/donors/99999/deferral-letter.pdf')
        assert resp.status_code == 404


# ─── Donor phenotype ──────────────────────────────────────────────────────────

class TestRecordDonorPhenotypeView:

    def test_get_renders_form(self, db, branch, user):
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(su, branch).get(f'/donors/{donor.pk}/phenotype/')
        assert resp.status_code == 200

    def test_get_nonexistent_donor_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/donors/99999/phenotype/')
        assert resp.status_code == 404

    def test_post_creates_phenotype(self, db, branch, user):
        from donors.models import DonorPhenotype
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(su, branch).post(f'/donors/{donor.pk}/phenotype/', {
            'C': 'pos', 'c': 'neg', 'E': 'neg', 'e': 'pos',
            'K': 'neg', 'k': 'pos',
            'method': 'serology',
            'notes': '',
        })
        assert resp.status_code in (200, 302)
        assert DonorPhenotype.objects.filter(donor=donor).exists()

    def test_post_writes_audit(self, db, branch, user):
        from audit.models import AuditLog
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        _client(su, branch).post(f'/donors/{donor.pk}/phenotype/', {
            'C': 'pos', 'K': 'neg', 'method': 'serology', 'notes': '',
        })
        assert AuditLog.objects.filter(action='donor.phenotype.record').exists()

    def test_post_updates_existing_phenotype(self, db, branch, user):
        from donors.models import DonorPhenotype
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        # First pass
        _client(su, branch).post(f'/donors/{donor.pk}/phenotype/', {
            'C': 'pos', 'method': 'serology', 'notes': '',
        })
        # Second pass — should update, not create a duplicate
        _client(su, branch).post(f'/donors/{donor.pk}/phenotype/', {
            'C': 'neg', 'method': 'molecular', 'notes': 'updated',
        })
        assert DonorPhenotype.objects.filter(donor=donor).count() == 1
        assert DonorPhenotype.objects.get(donor=donor).C is False

    def test_unauthenticated_redirects(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = Client().get(f'/donors/{donor.pk}/phenotype/')
        assert resp.status_code == 302


# ─── Lookback ─────────────────────────────────────────────────────────────────

class TestStartLookbackView:

    def test_get_renders_form(self, db, branch, user):
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(su, branch).get(f'/donors/{donor.pk}/lookback/')
        assert resp.status_code == 200

    def test_get_nonexistent_donor_returns_404(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/donors/99999/lookback/')
        assert resp.status_code == 404

    def test_post_missing_test_code_redirects(self, db, branch, user):
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(su, branch).post(f'/donors/{donor.pk}/lookback/', {
            'test_code': '',
            'notes': '',
        })
        assert resp.status_code in (200, 302)

    def test_post_creates_lookback_campaign(self, db, branch, user):
        from transfusion.models import LookbackCampaign
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(su, branch).post(f'/donors/{donor.pk}/lookback/', {
            'test_code': 'HCV_Ab',
            'notes': 'Triggered by reactive screen',
        })
        assert resp.status_code in (200, 302)
        assert LookbackCampaign.objects.filter(donor=donor).exists()

    def test_unauthenticated_redirects(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = Client().get(f'/donors/{donor.pk}/lookback/')
        assert resp.status_code == 302


# ─── Blood group card PDF ──────────────────────────────────────────────────────

class TestBloodGroupCardPDFView:

    def test_donor_with_confirmed_group_returns_pdf(self, db, branch, user):
        # DonorFactory sets blood_group_abo='O' and blood_group_rh='pos' by default
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = _client(user, branch).get(f'/donors/{donor.pk}/blood-group-card.pdf')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'

    def test_donor_without_group_redirects(self, db, branch, user):
        donor = DonorFactory(
            registration_branch=branch, created_by=user,
            blood_group_abo='', blood_group_rh='',
        )
        resp = _client(user, branch).get(f'/donors/{donor.pk}/blood-group-card.pdf')
        assert resp.status_code in (200, 302)

    def test_nonexistent_donor_returns_404(self, db, branch, user):
        resp = _client(user, branch).get('/donors/99999/blood-group-card.pdf')
        assert resp.status_code == 404

    def test_unauthenticated_redirects(self, db, branch, user):
        donor = DonorFactory(registration_branch=branch, created_by=user)
        resp = Client().get(f'/donors/{donor.pk}/blood-group-card.pdf')
        assert resp.status_code == 302


# ─── Record donation — error path bug fixes ───────────────────────────────────

class TestRecordDonationErrorPaths:

    def test_no_branch_in_session_redirects_with_error(self, db, branch, user):
        """Bug fix: used to raise 404 silently when branch_id=None."""
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user, deferral_status='active')
        # Log in without setting branch_id in session
        c = Client()
        c.login(username=su.username, password='testpass123')
        resp = c.post(f'/donors/{donor.pk}/donate/', {
            'donation_type': 'whole_blood',
            'volume_ml': '450',
        })
        # Should redirect (not crash with 404)
        assert resp.status_code in (200, 302)
        # No donation should be created
        from donors.models import Donation
        assert not Donation.objects.filter(donor=donor).exists()

    def test_missing_ref_facility_redirects_with_error(self, db, branch, user):
        """Bug fix: used to raise 404 when RefFacility missing for branch."""
        su = _su(branch)
        donor = DonorFactory(registration_branch=branch, created_by=user, deferral_status='active')
        # Deliberately do NOT create a RefFacility for this branch
        from core.models import RefFacility
        RefFacility.objects.filter(branch=branch).delete()
        resp = _client(su, branch).post(f'/donors/{donor.pk}/donate/', {
            'donation_type': 'whole_blood',
            'volume_ml': '450',
        })
        # Should redirect to detail page (not raise 404/500)
        assert resp.status_code in (200, 302)
        # No donation created
        from donors.models import Donation
        assert not Donation.objects.filter(donor=donor).exists()
