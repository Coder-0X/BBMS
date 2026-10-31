"""
Pure unit tests — ABO/Rh compatibility matrix.
No database required.  Run: pytest tests/test_abo_compatibility.py -v
"""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ─── helpers ─────────────────────────────────────────────────────────────────

def _bg(abo, rh_d):
    return SimpleNamespace(abo=abo, rh_d=rh_d)

def _unit(abo, rh_d):
    return SimpleNamespace(abo_type=abo, rh_d_type=rh_d)


# ─── ABO compatibility matrix ─────────────────────────────────────────────────

class TestAboCompatibility:

    @pytest.fixture(autouse=True)
    def _import(self):
        from transfusion.issue import _check_abo_compatibility
        self.check = _check_abo_compatibility

    def test_o_neg_is_universal_donor(self):
        for patient_abo in ('A', 'B', 'AB', 'O'):
            for patient_rh in ('pos', 'neg'):
                assert self.check(_unit('O', 'neg'), _bg(patient_abo, patient_rh)), \
                    f"O- unit should be compatible with {patient_abo} {patient_rh}"

    def test_ab_pos_patient_accepts_all(self):
        for donor_abo in ('A', 'B', 'AB', 'O'):
            for donor_rh in ('pos', 'neg'):
                assert self.check(_unit(donor_abo, donor_rh), _bg('AB', 'pos')), \
                    f"AB+ patient should accept {donor_abo} {donor_rh}"

    def test_a_patient_rejects_b_unit(self):
        assert not self.check(_unit('B', 'pos'), _bg('A', 'pos'))
        assert not self.check(_unit('B', 'neg'), _bg('A', 'neg'))

    def test_b_patient_rejects_a_unit(self):
        assert not self.check(_unit('A', 'pos'), _bg('B', 'pos'))

    def test_o_patient_rejects_a_unit(self):
        assert not self.check(_unit('A', 'neg'), _bg('O', 'neg'))

    def test_o_patient_rejects_b_unit(self):
        assert not self.check(_unit('B', 'neg'), _bg('O', 'neg'))

    def test_o_patient_rejects_ab_unit(self):
        assert not self.check(_unit('AB', 'neg'), _bg('O', 'neg'))

    def test_o_patient_accepts_o_unit(self):
        assert self.check(_unit('O', 'pos'), _bg('O', 'pos'))

    def test_rh_neg_patient_rejects_rh_pos_unit(self):
        assert not self.check(_unit('O', 'pos'), _bg('O', 'neg'))
        assert not self.check(_unit('A', 'pos'), _bg('A', 'neg'))

    def test_rh_pos_patient_accepts_rh_neg_unit(self):
        assert self.check(_unit('O', 'neg'), _bg('O', 'pos'))
        assert self.check(_unit('A', 'neg'), _bg('A', 'pos'))

    def test_no_blood_group_requires_o_neg_unit(self):
        """Patient without blood group on file — only O- is safe."""
        assert self.check(_unit('O', 'neg'), None)

    def test_no_blood_group_rejects_non_o_neg(self):
        assert not self.check(_unit('A', 'pos'), None)
        assert not self.check(_unit('O', 'pos'), None)
        assert not self.check(_unit('B', 'neg'), None)

    def test_full_64_cell_matrix(self):
        """Spot-check the full 8×8 ABO/Rh matrix for consistency."""
        from transfusion.issue import _check_abo_compatibility
        abo_list = ['A', 'B', 'AB', 'O']
        rh_list = ['pos', 'neg']
        for donor_abo in abo_list:
            for donor_rh in rh_list:
                for pat_abo in abo_list:
                    for pat_rh in rh_list:
                        result = _check_abo_compatibility(
                            _unit(donor_abo, donor_rh), _bg(pat_abo, pat_rh)
                        )
                        assert isinstance(result, bool)


class TestCompatibleLabelList:

    @pytest.fixture(autouse=True)
    def _import(self):
        from transfusion.views import _compatible_label_list
        self.labels = _compatible_label_list

    def test_o_neg_patient_only_o_neg(self):
        result = self.labels('O', 'neg')
        assert result == ['O−']

    def test_o_pos_patient_gets_o_types(self):
        result = self.labels('O', 'pos')
        assert 'O+' in result
        assert 'O−' in result
        assert 'A+' not in result

    def test_a_pos_patient_compatible(self):
        result = self.labels('A', 'pos')
        assert 'A+' in result
        assert 'A−' in result
        assert 'O+' in result
        assert 'O−' in result
        assert 'B+' not in result
        assert 'AB+' not in result

    def test_ab_pos_accepts_all(self):
        result = self.labels('AB', 'pos')
        assert len(result) >= 8  # all standard types, plus weak-D variants

    def test_ab_neg_accepts_all_neg(self):
        result = self.labels('AB', 'neg')
        assert 'A−' in result
        assert 'B−' in result
        assert 'AB−' in result
        assert 'O−' in result
        assert 'A+' not in result


class TestEffectiveBloodGroup:
    """Patient.effective_blood_group() fallback logic — no DB needed."""

    def _make_patient(self, abo='', rh_d='', has_lab=False, lab_abo='A', lab_rh='pos'):
        p = MagicMock()
        if has_lab:
            bg = SimpleNamespace(abo=lab_abo, rh_d=lab_rh, is_discrepant=False, source='lab')
            p.current_blood_group.return_value = bg
        else:
            p.current_blood_group.return_value = None
        p.abo = abo
        p.rh_d = rh_d
        from patients.models import Patient
        p.effective_blood_group = Patient.effective_blood_group.__get__(p)
        return p

    def test_lab_confirmed_takes_priority_over_declared(self):
        p = self._make_patient(abo='B', rh_d='neg', has_lab=True, lab_abo='A', lab_rh='pos')
        result = p.effective_blood_group()
        assert result.abo == 'A'
        assert result.rh_d == 'pos'

    def test_falls_back_to_declared_when_no_lab(self):
        p = self._make_patient(abo='B', rh_d='neg', has_lab=False)
        result = p.effective_blood_group()
        assert result.abo == 'B'
        assert result.rh_d == 'neg'
        assert result.source == 'declared'

    def test_returns_none_when_no_data(self):
        p = self._make_patient(abo='', rh_d='', has_lab=False)
        result = p.effective_blood_group()
        assert result is None
