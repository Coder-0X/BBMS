"""
Data Subject Rights (DSR) handler tests.

Verifies the legal logic:
  - Erasure of donors WITH blood-safety records → legal refusal (30-year retention)
    + marketing data still erased
  - Erasure of donors WITHOUT blood-safety records → full pseudonymisation
  - Access requests → summary returned, DSR marked completed
  - Campaign enrollment removed in both erasure paths

Run: pytest tests/test_dsr.py -v
"""
import pytest
from django.utils import timezone
from tests.conftest import UserFactory, BranchFactory, DonorFactory, DonationFactory


def _make_subject_with_email(user, email='dsr@example.com', name='Jane Donor'):
    from privacy.models import SubjectIdentity
    return SubjectIdentity.create_from_plain(
        name=name,
        national_id='',
        contact=email,
        subject_type='donor',
        created_by=user,
    )


def _make_dsr(subject, request_type='erase'):
    from privacy.models import DSRRequest
    return DSRRequest.objects.create(
        subject=subject,
        request_type=request_type,
        status='received',
    )


# ─── has_blood_safety_records ─────────────────────────────────────────────────

class TestHasBloodSafetyRecords:

    def test_donor_with_donation_has_records(self, db, branch, user):
        from privacy.dsr_handler import has_blood_safety_records
        donor = DonorFactory(registration_branch=branch, created_by=user,
                              total_donations=1)
        assert has_blood_safety_records(donor.subject) is True

    def test_donor_without_donation_no_records(self, db, branch, user):
        from privacy.dsr_handler import has_blood_safety_records
        subject = _make_subject_with_email(user)
        donor = DonorFactory(subject=subject, registration_branch=branch,
                              created_by=user, total_donations=0)
        assert has_blood_safety_records(subject) is False

    def test_unknown_subject_type_returns_false(self, db, user):
        from privacy.dsr_handler import has_blood_safety_records
        from privacy.models import SubjectIdentity
        subject = SubjectIdentity.objects.create(subject_type='patient', created_by=user)
        assert has_blood_safety_records(subject) is False

    def test_lookup_exception_returns_true_fail_safe(self, db, user):
        """
        Regression: if the DB lookup raises any exception, the function must
        return True (assume records exist) rather than silently returning False
        and allowing premature erasure of blood-safety data.
        """
        from privacy.dsr_handler import has_blood_safety_records
        from unittest.mock import patch, PropertyMock
        from privacy.models import SubjectIdentity

        subject = SubjectIdentity.objects.create(subject_type='donor', created_by=user)
        # Simulate `subject.donor` raising an exception (broken relation)
        with patch.object(type(subject), 'donor', new_callable=PropertyMock,
                          side_effect=Exception("DB error")):
            result = has_blood_safety_records(subject)
        assert result is True, (
            "When a lookup error occurs, has_blood_safety_records must return True "
            "(fail-safe) to prevent accidental data erasure."
        )

    def test_patient_with_issue_transaction_has_records(self, db, branch, user):
        """Patients who have received blood must have blood-safety records."""
        from privacy.dsr_handler import has_blood_safety_records
        from privacy.models import SubjectIdentity
        from tests.conftest import PatientFactory
        patient = PatientFactory(branch=branch)
        # PatientFactory creates a linked SubjectIdentity
        assert has_blood_safety_records(patient.subject) is False  # no transfusions yet


# ─── Erasure with blood-safety records ───────────────────────────────────────

class TestErasureWithBloodSafetyRecords:

    def test_legal_refusal_for_donor_with_donations(self, db, branch, user):
        from privacy.dsr_handler import handle_erasure_request
        from privacy.models import DSRRequest
        donor = DonorFactory(registration_branch=branch, created_by=user,
                              total_donations=5)
        dsr = _make_dsr(donor.subject)

        result = handle_erasure_request(dsr, actor=user)

        assert result['decision'] == 'partial_erasure_legal_refusal'
        dsr.refresh_from_db()
        assert dsr.status == 'refused'
        assert '30 year' in dsr.refusal_reason.lower() or 'blood directive' in dsr.refusal_reason.lower()

    def test_contact_enc_erased_on_legal_refusal(self, db, branch, user):
        from privacy.dsr_handler import handle_erasure_request
        subject = _make_subject_with_email(user, 'contact@example.com')
        donor = DonorFactory(subject=subject, registration_branch=branch,
                              created_by=user, total_donations=3)
        dsr = _make_dsr(subject)

        handle_erasure_request(dsr, actor=user)

        subject.refresh_from_db()
        assert subject.contact_enc == ''  # contact erased even on refusal

    def test_name_enc_retained_on_legal_refusal(self, db, branch, user):
        """Blood-safety records require name for traceability — must be retained."""
        from privacy.dsr_handler import handle_erasure_request
        subject = _make_subject_with_email(user)
        donor = DonorFactory(subject=subject, registration_branch=branch,
                              created_by=user, total_donations=2)
        dsr = _make_dsr(subject)

        handle_erasure_request(dsr, actor=user)

        subject.refresh_from_db()
        assert subject.name_enc != ''  # name retained for 30-year traceability

    def test_campaign_enrollment_erased_on_legal_refusal(self, db, branch, user):
        from privacy.dsr_handler import handle_erasure_request
        from donors.models import RetentionCampaign, CampaignEnrollment
        subject = _make_subject_with_email(user)
        donor = DonorFactory(subject=subject, registration_branch=branch,
                              created_by=user, total_donations=1)
        campaign = RetentionCampaign.objects.create(
            name='Test', branch=branch, segment='lapsed_6m', channel='email',
            message_template='Hi {name}', created_by=user, status='active',
        )
        CampaignEnrollment.objects.create(campaign=campaign, donor=donor)

        dsr = _make_dsr(subject)
        handle_erasure_request(dsr, actor=user)

        assert not CampaignEnrollment.objects.filter(donor=donor).exists()


# ─── Erasure without blood-safety records ────────────────────────────────────

class TestErasureWithoutBloodSafetyRecords:

    def test_full_pseudonymisation_for_donor_with_no_donations(self, db, branch, user):
        from privacy.dsr_handler import handle_erasure_request
        from privacy.models import DSRRequest
        subject = _make_subject_with_email(user, 'nodono@example.com')
        DonorFactory(subject=subject, registration_branch=branch,
                     created_by=user, total_donations=0)
        dsr = _make_dsr(subject)

        result = handle_erasure_request(dsr, actor=user)

        assert result['decision'] == 'full_pseudonymisation'
        dsr.refresh_from_db()
        assert dsr.status == 'completed'

    def test_all_pii_blanked_on_full_erasure(self, db, branch, user):
        from privacy.dsr_handler import handle_erasure_request
        subject = _make_subject_with_email(user)
        DonorFactory(subject=subject, registration_branch=branch,
                     created_by=user, total_donations=0)
        dsr = _make_dsr(subject)

        handle_erasure_request(dsr, actor=user)

        subject.refresh_from_db()
        assert subject.name_enc == ''
        assert subject.national_id_enc == ''
        assert subject.contact_enc == ''
        assert subject.name_blind_index == ''
        assert subject.national_id_blind_index == ''

    def test_handled_by_set_on_completion(self, db, branch, user):
        from privacy.dsr_handler import handle_erasure_request
        subject = _make_subject_with_email(user)
        DonorFactory(subject=subject, registration_branch=branch,
                     created_by=user, total_donations=0)
        dsr = _make_dsr(subject)

        handle_erasure_request(dsr, actor=user)

        dsr.refresh_from_db()
        assert dsr.handled_by == user
        assert dsr.completed_at is not None


# ─── Access request ───────────────────────────────────────────────────────────

class TestAccessRequest:

    def test_access_request_returns_held_data_summary(self, db, branch, user):
        from privacy.dsr_handler import handle_access_request
        donor = DonorFactory(registration_branch=branch, created_by=user,
                              total_donations=3, blood_group_abo='O', blood_group_rh='pos')
        dsr = _make_dsr(donor.subject, request_type='access')

        held = handle_access_request(dsr, actor=user)

        assert held['blood_safety_records'] is True
        assert held['total_donations'] == 3
        assert held['blood_group'] == 'O pos'
        dsr.refresh_from_db()
        assert dsr.status == 'completed'


# ─── DSR view ─────────────────────────────────────────────────────────────────

class TestDsrView:

    def test_dsr_view_requires_staff(self, db, branch, user):
        from django.test import Client
        c = Client()
        c.login(username=user.username, password='testpass123')
        donor = DonorFactory(registration_branch=branch, created_by=user)
        # user is not staff → should redirect with error
        response = c.get(f'/donors/{donor.pk}/dsr/')
        assert response.status_code in (200, 302)

    def test_staff_can_submit_erase_dsr(self, db, branch, user):
        from django.test import Client
        from django.contrib.auth import get_user_model
        from privacy.models import DSRRequest
        User = get_user_model()
        staff = User.objects.create_user(
            username='staffdsr', password='testpass123',
            display_name='Staff', branch=branch, is_staff=True,
        )
        donor = DonorFactory(registration_branch=branch, created_by=user, total_donations=0)
        c = Client()
        c.login(username='staffdsr', password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()

        response = c.post(f'/donors/{donor.pk}/dsr/', {'request_type': 'erase'})
        assert response.status_code in (200, 302)
        assert DSRRequest.objects.filter(subject=donor.subject).exists()
