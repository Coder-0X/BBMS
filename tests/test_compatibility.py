"""
Unit tests for ABO/Rh compatibility and issue safety checks.
These are the most safety-critical functions in the system.

Run with: python manage.py test tests.test_compatibility
"""
from django.test import TestCase
from unittest.mock import MagicMock, patch
from types import SimpleNamespace


class AboCompatibilityTests(TestCase):
    """Test _check_abo_compatibility from transfusion.issue."""

    def setUp(self):
        from transfusion.issue import _check_abo_compatibility
        self.check = _check_abo_compatibility

    def _bg(self, abo, rh_d):
        return SimpleNamespace(abo=abo, rh_d=rh_d)

    def _unit(self, abo, rh_d):
        return SimpleNamespace(abo_type=abo, rh_d_type=rh_d)

    def test_o_neg_universal_donor(self):
        for patient_abo in ('A', 'B', 'AB', 'O'):
            for patient_rh in ('pos', 'neg'):
                self.assertTrue(
                    self.check(self._unit('O', 'neg'), self._bg(patient_abo, patient_rh)),
                    f"O- should be compatible with {patient_abo} {patient_rh}",
                )

    def test_ab_pos_accepts_all(self):
        for donor_abo in ('A', 'B', 'AB', 'O'):
            for donor_rh in ('pos', 'neg'):
                self.assertTrue(
                    self.check(self._unit(donor_abo, donor_rh), self._bg('AB', 'pos')),
                    f"AB+ patient should accept {donor_abo} {donor_rh}",
                )

    def test_a_patient_rejects_b_unit(self):
        self.assertFalse(self.check(self._unit('B', 'pos'), self._bg('A', 'pos')))

    def test_b_patient_rejects_a_unit(self):
        self.assertFalse(self.check(self._unit('A', 'pos'), self._bg('B', 'pos')))

    def test_rh_neg_patient_rejects_rh_pos(self):
        self.assertFalse(self.check(self._unit('O', 'pos'), self._bg('O', 'neg')))

    def test_rh_pos_patient_accepts_rh_neg(self):
        self.assertTrue(self.check(self._unit('O', 'neg'), self._bg('O', 'pos')))

    def test_no_blood_group_requires_o_neg_unit(self):
        self.assertTrue(self.check(self._unit('O', 'neg'), None))

    def test_no_blood_group_rejects_non_o_neg(self):
        self.assertFalse(self.check(self._unit('A', 'pos'), None))
        self.assertFalse(self.check(self._unit('O', 'pos'), None))

    def test_o_patient_rejects_a_unit(self):
        self.assertFalse(self.check(self._unit('A', 'neg'), self._bg('O', 'neg')))

    def test_o_patient_accepts_o_unit(self):
        self.assertTrue(self.check(self._unit('O', 'pos'), self._bg('O', 'pos')))


class CompatibleTypeLabelTests(TestCase):
    """Test _compatible_label_list from transfusion.views."""

    def test_a_pos_patient_compatible_types(self):
        from transfusion.views import _compatible_label_list
        labels = _compatible_label_list('A', 'pos')
        # A+ can receive A+, A−, O+, O−
        self.assertIn('A+', labels)
        self.assertIn('A−', labels)
        self.assertIn('O+', labels)
        self.assertIn('O−', labels)
        # Should NOT receive B or AB
        self.assertNotIn('B+', labels)
        self.assertNotIn('AB+', labels)

    def test_o_neg_patient_only_o_neg(self):
        from transfusion.views import _compatible_label_list
        labels = _compatible_label_list('O', 'neg')
        self.assertEqual(labels, ['O−'])

    def test_ab_neg_patient_compatible_types(self):
        from transfusion.views import _compatible_label_list
        labels = _compatible_label_list('AB', 'neg')
        # AB- can receive all ABO types but only Rh- (or weak D? no — neg only for RBC)
        self.assertIn('A−', labels)
        self.assertIn('B−', labels)
        self.assertIn('O−', labels)
        self.assertIn('AB−', labels)
        # Should NOT receive Rh+ donors (for RBC)
        self.assertNotIn('A+', labels)


class PatientEffectiveBloodGroupTests(TestCase):
    """Test Patient.effective_blood_group fallback logic."""

    def _make_patient(self, abo='', rh_d='', has_lab=False):
        p = MagicMock()
        if has_lab:
            bg = SimpleNamespace(abo='A', rh_d='pos', is_discrepant=False, method='tube')
            p.current_blood_group.return_value = bg
        else:
            p.current_blood_group.return_value = None
        p.abo = abo
        p.rh_d = rh_d
        # Reuse the real method
        from patients.models import Patient
        p.effective_blood_group = Patient.effective_blood_group.__get__(p)
        return p

    def test_lab_confirmed_takes_priority(self):
        p = self._make_patient(abo='B', rh_d='neg', has_lab=True)
        result = p.effective_blood_group()
        self.assertEqual(result.abo, 'A')
        self.assertEqual(result.rh_d, 'pos')

    def test_falls_back_to_declared(self):
        p = self._make_patient(abo='B', rh_d='neg', has_lab=False)
        result = p.effective_blood_group()
        self.assertEqual(result.abo, 'B')
        self.assertEqual(result.rh_d, 'neg')
        self.assertEqual(result.source, 'declared')

    def test_returns_none_when_no_data(self):
        p = self._make_patient(abo='', rh_d='', has_lab=False)
        result = p.effective_blood_group()
        self.assertIsNone(result)


class ElectronicXmEligibilityTests(TestCase):
    """Test the electronic XM gate logic."""

    def _make_patient(self, confirmed_count=2, latest_screen_result='negative',
                      has_significant_ab=False):
        from patients.models import PatientBloodGroup, PatientAntibody
        p = MagicMock()
        # blood_groups queryset mock
        bg_qs = MagicMock()
        bg_qs.filter.return_value.count.return_value = confirmed_count
        p.blood_groups = bg_qs
        return p

    def _make_unit(self, has_abo=True):
        u = MagicMock()
        u.abo_type = 'A' if has_abo else ''
        return u

    def test_all_gates_pass_returns_empty(self):
        from transfusion.views import _check_electronic_xm_eligibility
        with patch('transfusion.models.AntibodyScreen') as MockScreen, \
             patch('patients.models.PatientAntibody') as MockAb:

            screen = MagicMock()
            screen.overall_result = 'negative'
            MockScreen.objects.filter.return_value.order_by.return_value.first.return_value = screen
            MockAb.objects.filter.return_value.exists.return_value = False

            patient = self._make_patient(confirmed_count=2)
            unit = self._make_unit(has_abo=True)

            reasons = _check_electronic_xm_eligibility(patient, unit)
            self.assertEqual(reasons, [])

    def test_insufficient_abo_determinations(self):
        from transfusion.views import _check_electronic_xm_eligibility
        with patch('transfusion.models.AntibodyScreen') as MockScreen, \
             patch('patients.models.PatientAntibody') as MockAb:

            screen = MagicMock()
            screen.overall_result = 'negative'
            MockScreen.objects.filter.return_value.order_by.return_value.first.return_value = screen
            MockAb.objects.filter.return_value.exists.return_value = False

            patient = self._make_patient(confirmed_count=1)
            unit = self._make_unit(has_abo=True)

            reasons = _check_electronic_xm_eligibility(patient, unit)
            self.assertTrue(any('ABO' in r or 'determination' in r for r in reasons))

    def test_positive_antibody_screen_blocks(self):
        from transfusion.views import _check_electronic_xm_eligibility
        with patch('transfusion.models.AntibodyScreen') as MockScreen, \
             patch('patients.models.PatientAntibody') as MockAb:

            screen = MagicMock()
            screen.overall_result = 'positive'
            MockScreen.objects.filter.return_value.order_by.return_value.first.return_value = screen
            MockAb.objects.filter.return_value.exists.return_value = False

            patient = self._make_patient(confirmed_count=2)
            unit = self._make_unit(has_abo=True)

            reasons = _check_electronic_xm_eligibility(patient, unit)
            self.assertTrue(any('screen' in r.lower() or 'antibody' in r.lower() for r in reasons))

    def test_unconfirmed_unit_abo_blocks(self):
        from transfusion.views import _check_electronic_xm_eligibility
        with patch('transfusion.models.AntibodyScreen') as MockScreen, \
             patch('patients.models.PatientAntibody') as MockAb:

            screen = MagicMock()
            screen.overall_result = 'negative'
            MockScreen.objects.filter.return_value.order_by.return_value.first.return_value = screen
            MockAb.objects.filter.return_value.exists.return_value = False

            patient = self._make_patient(confirmed_count=2)
            unit = self._make_unit(has_abo=False)

            reasons = _check_electronic_xm_eligibility(patient, unit)
            self.assertTrue(any('unit' in r.lower() or 'ABO' in r for r in reasons))
