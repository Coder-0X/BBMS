"""
Safety-critical tests — all must pass before any deployment.
Tests individual check functions and critical paths in issue_unit.
Run: pytest tests/test_safety.py -v -m safety_critical
"""
import pytest
from datetime import timedelta
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone

from tests.conftest import (
    BloodUnitFactory, PatientFactory, DonorFactory, DonationFactory,
    UserFactory, BranchFactory, BloodRequestFactory,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _unit(abo='O', rh_d='neg', is_irradiated=False, is_cmv_negative=False,
          is_leukoreduced=False, antigen_negative_set=None):
    u = MagicMock()
    u.abo_type = abo
    u.rh_d_type = rh_d
    u.is_irradiated = is_irradiated
    u.is_cmv_negative = is_cmv_negative
    u.is_leukoreduced = is_leukoreduced
    u.antigen_negative_set = antigen_negative_set or {}
    return u


def _patient_with_requirements(*requirements):
    """requirements: list of (requirement_type, antigen_spec) tuples"""
    p = MagicMock()
    reqs = []
    for req_type, antigen_spec in requirements:
        r = MagicMock()
        r.requirement = req_type
        r.antigen_spec = antigen_spec
        reqs.append(r)
    p.active_special_requirements.return_value = reqs
    return p


def _patient_with_antibody(specificity, antigen_system='Kell', clinical_significance='significant'):
    p = MagicMock()
    p.active_special_requirements.return_value = []
    ab = MagicMock()
    ab.specificity = specificity
    ab.antigen_system = antigen_system
    ab.clinical_significance = clinical_significance
    ab.status = 'identified'
    return p, ab


# ─── ABO / Unit status guards ─────────────────────────────────────────────────

class TestAboGuardsAtIssue:
    """Test ABO check via direct function call."""

    @pytest.mark.safety_critical
    def test_b_unit_rejected_for_a_patient(self):
        from transfusion.issue import _check_abo_compatibility
        unit = SimpleNamespace(abo_type='B', rh_d_type='pos')
        bg = SimpleNamespace(abo='A', rh_d='pos')
        assert not _check_abo_compatibility(unit, bg)

    @pytest.mark.safety_critical
    def test_rh_pos_unit_rejected_for_rh_neg_patient(self):
        from transfusion.issue import _check_abo_compatibility
        unit = SimpleNamespace(abo_type='O', rh_d_type='pos')
        bg = SimpleNamespace(abo='O', rh_d='neg')
        assert not _check_abo_compatibility(unit, bg)

    @pytest.mark.safety_critical
    def test_no_blood_group_blocks_non_o_neg(self):
        from transfusion.issue import _check_abo_compatibility
        for abo in ('A', 'B', 'AB'):
            unit = SimpleNamespace(abo_type=abo, rh_d_type='neg')
            assert not _check_abo_compatibility(unit, None)

    @pytest.mark.safety_critical
    def test_no_blood_group_allows_o_neg(self):
        from transfusion.issue import _check_abo_compatibility
        unit = SimpleNamespace(abo_type='O', rh_d_type='neg')
        assert _check_abo_compatibility(unit, None)


class TestNonIssuableStatusBlocked:
    """Test that non-issuable unit statuses are blocked before crossmatch/ABO check."""

    @pytest.mark.safety_critical
    @pytest.mark.parametrize('bad_status', [
        'quarantined', 'in_testing', 'failed_qc', 'expired',
        'recalled', 'quarantined_holdback', 'wasted', 'destroyed',
    ])
    def test_non_issuable_status_raises(self, db, branch, user, bad_status):
        from inventory.state_machine import seed_transitions
        from transfusion.issue import issue_unit
        seed_transitions()
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(
            donation=donation, status=bad_status, owner_branch=branch,
            expiry_datetime=timezone.now() + timedelta(days=30),
        )
        patient = PatientFactory(created_by=user)
        request = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)

        with pytest.raises(ValidationError, match=bad_status):
            issue_unit(unit.pk, patient.pk, request.pk, user, timezone.now())

    @pytest.mark.safety_critical
    def test_expired_unit_blocked(self, db, branch, user):
        from inventory.state_machine import seed_transitions
        from transfusion.issue import issue_unit
        seed_transitions()
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(
            donation=donation, status='crossmatched', owner_branch=branch,
            expiry_datetime=timezone.now() - timedelta(hours=1),  # expired
        )
        patient = PatientFactory(created_by=user)
        request = BloodRequestFactory(patient=patient, branch=branch, requesting_physician=user)

        with pytest.raises(ValidationError, match='expired'):
            issue_unit(unit.pk, patient.pk, request.pk, user, timezone.now())


# ─── Special requirements enforcement ────────────────────────────────────────

class TestSpecialRequirementsEnforcement:

    @pytest.mark.safety_critical
    def test_irradiation_requirement_enforced(self):
        from transfusion.issue import _check_special_requirements
        unit = _unit(is_irradiated=False)
        patient = _patient_with_requirements(('irradiated', None))
        with pytest.raises(ValidationError, match='irradiated'):
            _check_special_requirements(unit, patient)

    @pytest.mark.safety_critical
    def test_irradiated_unit_passes(self):
        from transfusion.issue import _check_special_requirements
        unit = _unit(is_irradiated=True)
        patient = _patient_with_requirements(('irradiated', None))
        _check_special_requirements(unit, patient)  # must not raise

    @pytest.mark.safety_critical
    def test_cmv_negative_requirement_enforced(self):
        from transfusion.issue import _check_special_requirements
        unit = _unit(is_cmv_negative=False)
        patient = _patient_with_requirements(('cmv_negative', None))
        with pytest.raises(ValidationError, match='CMV'):
            _check_special_requirements(unit, patient)

    @pytest.mark.safety_critical
    def test_leukoreduced_requirement_enforced(self):
        from transfusion.issue import _check_special_requirements
        unit = _unit(is_leukoreduced=False)
        patient = _patient_with_requirements(('leukoreduced_only', None))
        with pytest.raises(ValidationError, match='leukoreduced'):
            _check_special_requirements(unit, patient)

    @pytest.mark.safety_critical
    def test_antigen_negative_requirement_enforced(self):
        from transfusion.issue import _check_special_requirements
        # Unit does NOT have K in negative set
        unit = _unit(antigen_negative_set={'E': True})
        patient = _patient_with_requirements(('antigen_negative', 'K'))
        with pytest.raises(ValidationError, match='K'):
            _check_special_requirements(unit, patient)

    @pytest.mark.safety_critical
    def test_antigen_negative_passes_when_unit_lacks_antigen(self):
        from transfusion.issue import _check_special_requirements
        # Unit has K in negative set (K=True means K-negative)
        unit = _unit(antigen_negative_set={'K': True})
        patient = _patient_with_requirements(('antigen_negative', 'K'))
        _check_special_requirements(unit, patient)  # must not raise

    @pytest.mark.safety_critical
    def test_antigen_negative_rejects_explicitly_positive_unit(self):
        """Regression: a unit CONFIRMED antigen-positive ({'K': False}) must be
        rejected for a K-negative requirement. Previously a key-presence check
        (`antigen not in neg_set`) let a known-K-positive unit through because the
        key existed regardless of its falsy value."""
        from transfusion.issue import _check_special_requirements
        # K present in dict but value False → unit tested K-POSITIVE
        unit = _unit(antigen_negative_set={'K': False})
        patient = _patient_with_requirements(('antigen_negative', 'K'))
        with pytest.raises(ValidationError, match='K'):
            _check_special_requirements(unit, patient)


# ─── Antibody history enforcement ────────────────────────────────────────────

class TestAntibodyAntigentCompatibility:

    @pytest.mark.safety_critical
    def test_anti_k_blocks_k_positive_unit(self, db, branch, user):
        from transfusion.issue import _check_antibody_antigen_compatibility
        from patients.models import PatientAntibody
        patient = PatientFactory(created_by=user)
        PatientAntibody.objects.create(
            patient=patient,
            specificity='anti-K',
            antigen_system='Kell',
            clinical_significance='significant',
            status='identified',
            first_identified_at=timezone.now(),
            first_identified_branch=branch,
            identified_by=user,
        )
        # Unit NOT K-negative (empty antigen set means untested / not negative)
        unit = MagicMock()
        unit.antigen_negative_set = {}
        with pytest.raises(ValidationError, match='anti-K'):
            _check_antibody_antigen_compatibility(unit, patient)

    @pytest.mark.safety_critical
    def test_anti_k_passes_for_k_negative_unit(self, db, branch, user):
        from transfusion.issue import _check_antibody_antigen_compatibility
        from patients.models import PatientAntibody
        patient = PatientFactory(created_by=user)
        PatientAntibody.objects.create(
            patient=patient,
            specificity='anti-K',
            antigen_system='Kell',
            clinical_significance='significant',
            status='historical_only',  # evanescent but still enforced
            first_identified_at=timezone.now(),
            first_identified_branch=branch,
            identified_by=user,
        )
        unit = MagicMock()
        unit.antigen_negative_set = {'K': True}  # K-negative
        _check_antibody_antigen_compatibility(unit, patient)  # must not raise

    @pytest.mark.safety_critical
    def test_historical_antibody_still_enforced(self, db, branch, user):
        """Even evanescent antibodies (status=historical_only) must be enforced."""
        from transfusion.issue import _check_antibody_antigen_compatibility
        from patients.models import PatientAntibody
        patient = PatientFactory(created_by=user)
        PatientAntibody.objects.create(
            patient=patient,
            specificity='anti-E',
            antigen_system='Rh',
            clinical_significance='significant',
            status='historical_only',
            first_identified_at=timezone.now(),
            first_identified_branch=branch,
            identified_by=user,
        )
        unit = MagicMock()
        unit.antigen_negative_set = {}  # E not confirmed negative
        with pytest.raises(ValidationError, match='anti-E'):
            _check_antibody_antigen_compatibility(unit, patient)


# ─── Directed / Autologous interlock ─────────────────────────────────────────

class TestDirectedAutologousInterlock:

    @pytest.mark.safety_critical
    def test_autologous_unit_blocked_for_wrong_patient(self, db, branch, user):
        from transfusion.issue import _check_directed_autologous
        patient_a = PatientFactory(created_by=user)
        patient_b = PatientFactory(created_by=user)

        unit = MagicMock()
        unit.donation.donation_purpose = 'autologous'
        unit.donation.intended_recipient = patient_a  # pre-deposited BY patient_a
        unit.did = 'TEST00000001'

        with pytest.raises(ValidationError):
            _check_directed_autologous(unit, patient_b)  # wrong patient

    @pytest.mark.safety_critical
    def test_directed_unit_blocked_for_wrong_patient(self, db, branch, user):
        from transfusion.issue import _check_directed_autologous
        patient_a = PatientFactory(created_by=user)
        patient_b = PatientFactory(created_by=user)

        unit = MagicMock()
        unit.donation.donation_purpose = 'directed'
        unit.donation.intended_recipient = patient_a
        unit.did = 'TEST00000002'

        with pytest.raises(ValidationError):
            _check_directed_autologous(unit, patient_b)

    @pytest.mark.safety_critical
    def test_allogeneic_unit_has_no_restriction(self, db, branch, user):
        from transfusion.issue import _check_directed_autologous
        patient = PatientFactory(created_by=user)
        unit = MagicMock()
        unit.donation.donation_purpose = 'allogeneic'
        _check_directed_autologous(unit, patient)  # must not raise


# ─── Separation of Duties ─────────────────────────────────────────────────────

class TestSeparationOfDuties:

    @pytest.mark.safety_critical
    def test_collector_cannot_issue(self, db, branch):
        from transfusion.issue import _check_sod
        collector = UserFactory(branch=branch)
        donor = DonorFactory(registration_branch=branch, created_by=collector)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=collector)
        unit = MagicMock()
        unit.donation_id = donation.pk
        unit.did = 'TEST00000003'
        # Same user tries to issue
        with pytest.raises(PermissionDenied, match='Separation of Duties'):
            _check_sod(unit, collector)

    @pytest.mark.safety_critical
    def test_different_user_can_issue(self, db, branch):
        from transfusion.issue import _check_sod
        collector = UserFactory(branch=branch)
        issuer = UserFactory(branch=branch)
        donor = DonorFactory(registration_branch=branch, created_by=collector)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=collector)
        unit = MagicMock()
        unit.donation_id = donation.pk
        # Different user — should not raise
        _check_sod(unit, issuer)


# ─── Neonatal requirements ────────────────────────────────────────────────────

class TestNeonatalRequirements:

    @pytest.mark.safety_critical
    def test_neonatal_non_irradiated_blocked(self, db, branch, user):
        from transfusion.issue import _check_neonatal_requirements
        unit = MagicMock()
        unit.is_irradiated = False
        unit.is_leukoreduced = True
        unit.is_cmv_negative = True
        unit.volume_ml = 20.0
        unit.component_type = None
        unit.collection_datetime = None

        blood_request = MagicMock()
        blood_request.is_neonatal = True
        blood_request.target_volume_ml = 100
        blood_request.neonatal_weight_kg = None

        patient = MagicMock()
        patient.dob = None
        patient.sex = 'M'

        with pytest.raises(ValidationError, match='[Ii]rradiat'):
            _check_neonatal_requirements(unit, blood_request, patient)

    @pytest.mark.safety_critical
    def test_neonatal_irradiated_cmv_safe_passes(self, db, branch, user):
        from transfusion.issue import _check_neonatal_requirements
        unit = MagicMock()
        unit.is_irradiated = True
        unit.is_leukoreduced = True  # leukoreduced = CMV safe
        unit.is_cmv_negative = False  # doesn't matter if leukoreduced
        unit.volume_ml = 20.0
        unit.component_type = None  # skip freshness check
        unit.collection_datetime = None

        blood_request = MagicMock()
        blood_request.is_neonatal = True
        blood_request.target_volume_ml = 50
        blood_request.neonatal_weight_kg = None  # skip weight/volume check

        patient = MagicMock()
        patient.dob = None
        patient.sex = 'M'

        # Should not raise
        _check_neonatal_requirements(unit, blood_request, patient)
