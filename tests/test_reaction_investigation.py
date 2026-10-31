"""
Reaction investigation workup tests.

Tests cover:
  - ReactionInvestigation model properties (haemolysis_positive, is_complete)
  - start_investigation view: creates investigation, redirects to update
  - investigation_update view: saves fields, completes with e-sign
  - reaction_detail view: renders correctly, shows investigation status
  - Edge cases: duplicate investigation blocked, DAT logic
"""
import pytest
from django.utils import timezone
from django.test import Client

from tests.conftest import (
    UserFactory, BranchFactory, DonorFactory, DonationFactory,
    BloodUnitFactory, PatientFactory, BloodRequestFactory,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_issue_transaction(branch, user):
    """Build a minimal IssueTransaction for testing reactions."""
    from audit.utils import create_signature
    from transfusion.models import BloodRequest, IssueTransaction

    donor = DonorFactory(registration_branch=branch, created_by=user)
    donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
    unit = BloodUnitFactory(
        donation=donation, owner_branch=branch, status='crossmatched',
    )
    patient = PatientFactory(created_by=user)
    request = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)

    esign = create_signature(
        signer=user, meaning='issue',
        payload_data={'unit': unit.did, 'patient': patient.pk},
    )
    tx = IssueTransaction.objects.create(
        blood_unit=unit,
        patient=patient,
        request=request,
        issued_by=user,
        issue_esign=esign,
        issued_at=timezone.now(),
        intended_branch=branch,
        abo_check_passed=True,
    )
    unit.status = 'issued'
    unit.save(update_fields=['status'])
    return tx


def _make_reaction(branch, user):
    """Record a minimal transfusion reaction."""
    from transfusion.haemovigilance import record_reaction
    tx = _make_issue_transaction(branch, user)
    reaction = record_reaction(
        issue_transaction=tx,
        reaction_type='FNHTR',
        onset_datetime=timezone.now(),
        severity='grade_1',
        imputability='possible',
        outcome='full_recovery',
        clinical_description='Mild fever during transfusion.',
        actor=user,
        reauth_at=None,
    )
    return reaction


# ─── Model properties ────────────────────────────────────────────────────────

class TestReactionInvestigationModel:

    def test_is_complete_false_when_no_completed_at(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(reaction=reaction, started_by=user)
        assert inv.is_complete is False

    def test_is_complete_true_after_completion(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(
            reaction=reaction, started_by=user,
            completed_at=timezone.now(), completed_by=user,
        )
        assert inv.is_complete is True

    def test_haemolysis_positive_with_positive_dat(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(
            reaction=reaction, started_by=user, dat_result='positive',
        )
        assert inv.haemolysis_positive is True

    def test_haemolysis_positive_with_severe_plasma_hb(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(
            reaction=reaction, started_by=user,
            dat_result='negative', plasma_haemoglobin='severe',
        )
        assert inv.haemolysis_positive is True

    def test_haemolysis_positive_false_when_all_absent(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(
            reaction=reaction, started_by=user,
            dat_result='negative',
            plasma_haemoglobin='absent',
            urine_haemoglobin='absent',
        )
        assert inv.haemolysis_positive is False


# ─── start_investigation view ─────────────────────────────────────────────────

class TestStartInvestigation:

    def test_start_creates_investigation_and_redirects(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        url = f'/transfusion/reaction/{reaction.pk}/investigation/start/'
        response = c.get(url)
        assert response.status_code == 302
        assert ReactionInvestigation.objects.filter(reaction=reaction).exists()

    def test_start_twice_redirects_to_existing(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        ReactionInvestigation.objects.create(reaction=reaction, started_by=user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        url = f'/transfusion/reaction/{reaction.pk}/investigation/start/'
        response = c.get(url)
        # Should not create a second one
        assert ReactionInvestigation.objects.filter(reaction=reaction).count() == 1
        assert response.status_code == 302


# ─── investigation_update view ────────────────────────────────────────────────

class TestInvestigationUpdate:

    def _base_payload(self):
        return {
            'repeat_abo_patient': 'A', 'repeat_abo_unit': 'A',
            'abo_discrepancy': 'no',
            'dat_result': 'negative', 'dat_specificity': '',
            'plasma_haemoglobin': 'absent', 'urine_haemoglobin': 'absent',
            'plasma_bilirubin_umol': '', 'plasma_ldh_iu': '',
            'repeat_antibody_screen': 'negative', 'new_antibody_identified': '',
            'unit_culture': 'not_done', 'unit_culture_organism': '',
            'patient_blood_culture': 'not_done',
            'dic_fibrinogen_g_l': '', 'dic_pt_seconds': '',
            'dic_aptt_seconds': '', 'dic_d_dimer': '',
            'conclusion': 'confirmed_non_haemolytic',
            'shot_category': 'FNHTR',
            'narrative': 'No haemolysis. FNHTR consistent with febrile reaction.',
        }

    def test_save_progress_updates_fields(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(reaction=reaction, started_by=user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        payload = {**self._base_payload(), 'save': '1'}
        response = c.post(f'/transfusion/reaction/{reaction.pk}/investigation/', payload)
        assert response.status_code == 302
        inv.refresh_from_db()
        assert inv.dat_result == 'negative'
        assert inv.conclusion == 'confirmed_non_haemolytic'
        assert inv.completed_at is None  # not completed yet

    def test_complete_sets_completed_at(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(reaction=reaction, started_by=user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        payload = {**self._base_payload(), 'complete': '1'}
        response = c.post(f'/transfusion/reaction/{reaction.pk}/investigation/', payload)
        assert response.status_code == 302
        inv.refresh_from_db()
        assert inv.completed_at is not None
        assert inv.completed_by == user
        assert inv.esign is not None

    def test_shot_reportable_mirrors_to_reaction(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(reaction=reaction, started_by=user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        payload = {**self._base_payload(), 'shot_reportable': 'on', 'complete': '1'}
        c.post(f'/transfusion/reaction/{reaction.pk}/investigation/', payload)
        reaction.refresh_from_db()
        assert reaction.reported_to_authority is True

    def test_abo_discrepancy_saved_correctly(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(reaction=reaction, started_by=user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        payload = {**self._base_payload(), 'abo_discrepancy': 'yes', 'save': '1'}
        c.post(f'/transfusion/reaction/{reaction.pk}/investigation/', payload)
        inv.refresh_from_db()
        assert inv.abo_discrepancy is True

    def test_numeric_fields_saved(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        inv = ReactionInvestigation.objects.create(reaction=reaction, started_by=user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        payload = {**self._base_payload(), 'plasma_bilirubin_umol': '42.5',
                   'plasma_ldh_iu': '380', 'save': '1'}
        c.post(f'/transfusion/reaction/{reaction.pk}/investigation/', payload)
        inv.refresh_from_db()
        assert float(inv.plasma_bilirubin_umol) == 42.5
        assert inv.plasma_ldh_iu == 380


# ─── reaction_detail view ────────────────────────────────────────────────────

class TestReactionDetailView:

    def test_reaction_detail_renders(self, db, branch, user):
        reaction = _make_reaction(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        response = c.get(f'/transfusion/reaction/{reaction.pk}/')
        assert response.status_code == 200
        assert b'Transfusion Reaction' in response.content

    def test_reaction_detail_shows_open_investigation_badge(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        ReactionInvestigation.objects.create(reaction=reaction, started_by=user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        response = c.get(f'/transfusion/reaction/{reaction.pk}/')
        assert b'In Progress' in response.content

    def test_reaction_detail_shows_complete_badge(self, db, branch, user):
        from transfusion.models import ReactionInvestigation
        reaction = _make_reaction(branch, user)
        ReactionInvestigation.objects.create(
            reaction=reaction, started_by=user,
            completed_at=timezone.now(), completed_by=user,
            conclusion='no_abnormality',
        )
        c = Client()
        c.login(username=user.username, password='testpass123')
        response = c.get(f'/transfusion/reaction/{reaction.pk}/')
        assert b'Complete' in response.content

    def test_reaction_detail_shows_open_workup_button_when_no_investigation(self, db, branch, user):
        reaction = _make_reaction(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        response = c.get(f'/transfusion/reaction/{reaction.pk}/')
        assert b'Open Investigation Workup' in response.content
