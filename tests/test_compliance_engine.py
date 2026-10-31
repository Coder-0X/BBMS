"""
Unit tests for the compliance rule engine.

Covers the 7 WHO/AABB hardcoded minimums (the rules that apply when no
branch ruleset is configured) and the check_donor_eligibility dispatcher.

Each rule is tested independently so a regression in one doesn't hide another.
"""
import pytest
from decimal import Decimal

from compliance.engine import check_donor_eligibility, RuleFailure


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _passing_donor_data():
    """Minimal data that passes all hardcoded rules for a male donor."""
    return {
        'age': 28,
        'weight_kg': 70,
        'hb_g_dl': 14.0,
        'bp_systolic': 120,
        'bp_diastolic': 80,
        'pulse': 72,
        'days_since_last_donation': None,  # First-time donor
        'deferral_status': 'active',
        'sex': 'M',
    }


def _rule_codes(failures):
    return {f.rule_kind for f in failures}


# ─── Branch with no ruleset (uses hardcoded minimums) ────────────────────────

@pytest.fixture
def branch_no_ruleset(db):
    """A branch with no active compliance ruleset — triggers hardcoded minimums."""
    from core.models import Branch
    return Branch.objects.create(
        name='No-Ruleset Branch',
        facility_code='NRS',
        active=True,
    )


# ─── Hardcoded minimum: AGE ───────────────────────────────────────────────────

class TestAgeRule:

    def test_age_below_minimum_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['age'] = 17  # Below 18
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'AGE' in _rule_codes(failures)

    def test_age_above_maximum_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['age'] = 66  # Above 65
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'AGE' in _rule_codes(failures)

    def test_age_exactly_18_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['age'] = 18
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'AGE' not in _rule_codes(failures)

    def test_age_exactly_65_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['age'] = 65
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'AGE' not in _rule_codes(failures)

    def test_age_none_skips_rule(self, db, branch_no_ruleset):
        """Missing value should not crash — rule is silently skipped."""
        data = _passing_donor_data()
        data['age'] = None
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'AGE' not in _rule_codes(failures)


# ─── Hardcoded minimum: WEIGHT ────────────────────────────────────────────────

class TestWeightRule:

    def test_weight_below_50kg_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['weight_kg'] = 49
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'WEIGHT' in _rule_codes(failures)

    def test_weight_exactly_50kg_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['weight_kg'] = 50
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'WEIGHT' not in _rule_codes(failures)

    def test_weight_none_skips_rule(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['weight_kg'] = None
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'WEIGHT' not in _rule_codes(failures)


# ─── Hardcoded minimum: HAEMOGLOBIN ──────────────────────────────────────────

class TestHaemoglobinRule:

    def test_hb_below_12_5_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['hb_g_dl'] = 12.0  # Below 12.5 g/dL
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'HB' in _rule_codes(failures)

    def test_hb_exactly_12_5_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['hb_g_dl'] = 12.5
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'HB' not in _rule_codes(failures)

    def test_hb_high_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['hb_g_dl'] = 17.5
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'HB' not in _rule_codes(failures)

    def test_hb_none_skips_rule(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['hb_g_dl'] = None
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'HB' not in _rule_codes(failures)


# ─── Hardcoded minimum: BLOOD PRESSURE ───────────────────────────────────────

class TestBloodPressureRules:

    def test_systolic_too_low_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['bp_systolic'] = 95  # Below 100
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'BP_SYSTOLIC' in _rule_codes(failures)

    def test_systolic_too_high_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['bp_systolic'] = 185  # Above 180
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'BP_SYSTOLIC' in _rule_codes(failures)

    def test_systolic_at_boundary_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['bp_systolic'] = 100
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'BP_SYSTOLIC' not in _rule_codes(failures)

    def test_diastolic_too_low_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['bp_diastolic'] = 55  # Below 60
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'BP_DIASTOLIC' in _rule_codes(failures)

    def test_diastolic_too_high_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['bp_diastolic'] = 105  # Above 100
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'BP_DIASTOLIC' in _rule_codes(failures)

    def test_diastolic_at_lower_boundary_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['bp_diastolic'] = 60
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'BP_DIASTOLIC' not in _rule_codes(failures)

    def test_diastolic_at_upper_boundary_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['bp_diastolic'] = 100
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'BP_DIASTOLIC' not in _rule_codes(failures)


# ─── Hardcoded minimum: PULSE ─────────────────────────────────────────────────

class TestPulseRule:

    def test_pulse_too_low_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['pulse'] = 55  # Below 60
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'PULSE' in _rule_codes(failures)

    def test_pulse_too_high_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['pulse'] = 105  # Above 100
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'PULSE' in _rule_codes(failures)

    def test_pulse_at_lower_boundary_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['pulse'] = 60
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'PULSE' not in _rule_codes(failures)

    def test_pulse_at_upper_boundary_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['pulse'] = 100
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'PULSE' not in _rule_codes(failures)


# ─── Hardcoded minimum: DONATION INTERVAL ────────────────────────────────────

class TestDonationIntervalRule:

    def test_interval_too_short_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['days_since_last_donation'] = 50  # Below 56-day minimum
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'DONATION_INTERVAL' in _rule_codes(failures)

    def test_interval_exactly_56_days_passes(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['days_since_last_donation'] = 56
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'DONATION_INTERVAL' not in _rule_codes(failures)

    def test_interval_none_skips_rule(self, db, branch_no_ruleset):
        """First-time donor has no prior donation — rule should be skipped."""
        data = _passing_donor_data()
        data['days_since_last_donation'] = None
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'DONATION_INTERVAL' not in _rule_codes(failures)


# ─── Deferral check ───────────────────────────────────────────────────────────

class TestDeferralCheck:

    def test_temporary_defer_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['deferral_status'] = 'temporary_defer'
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'DEFERRAL' in _rule_codes(failures)

    def test_permanent_defer_fails(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['deferral_status'] = 'permanent_defer'
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'DEFERRAL' in _rule_codes(failures)

    def test_active_status_no_deferral_failure(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['deferral_status'] = 'active'
        failures = check_donor_eligibility(branch_no_ruleset, data)
        assert 'DEFERRAL' not in _rule_codes(failures)


# ─── Fully passing donor ─────────────────────────────────────────────────────

class TestPassingDonor:

    def test_all_rules_pass_returns_empty_list(self, db, branch_no_ruleset):
        failures = check_donor_eligibility(branch_no_ruleset, _passing_donor_data())
        assert failures == []

    def test_multiple_failures_all_reported(self, db, branch_no_ruleset):
        """Multiple simultaneous failures should all be returned, not just the first."""
        data = _passing_donor_data()
        data['age'] = 17
        data['weight_kg'] = 40
        data['hb_g_dl'] = 11.0
        failures = check_donor_eligibility(branch_no_ruleset, data)
        codes = _rule_codes(failures)
        assert 'AGE' in codes
        assert 'WEIGHT' in codes
        assert 'HB' in codes

    def test_failure_includes_citation(self, db, branch_no_ruleset):
        data = _passing_donor_data()
        data['weight_kg'] = 40
        failures = check_donor_eligibility(branch_no_ruleset, data)
        weight_failure = next(f for f in failures if f.rule_kind == 'WEIGHT')
        assert weight_failure.citation  # Must have a WHO/AABB citation
        assert 'WHO' in weight_failure.citation or 'AABB' in weight_failure.citation

    def test_all_fields_none_returns_only_deferral_check(self, db, branch_no_ruleset):
        """All None values should skip individual rules but still check deferral."""
        data = {
            'age': None, 'weight_kg': None, 'hb_g_dl': None,
            'bp_systolic': None, 'bp_diastolic': None, 'pulse': None,
            'days_since_last_donation': None,
            'deferral_status': 'active', 'sex': 'M',
        }
        failures = check_donor_eligibility(branch_no_ruleset, data)
        # No rules fire when values are None, and deferral is active
        assert failures == []

    def test_between_operator_does_not_crash_when_t2_is_none(self, db, branch_no_ruleset):
        """Regression test: dict-eager-eval bug caused TypeError on 'gte' rules.
        Ensures the fix (lambda-deferred eval) works correctly for all operators."""
        data = _passing_donor_data()
        # weight_kg uses 'gte' operator with t2=None — the bug crashed here
        data['weight_kg'] = 45  # Below threshold — forces the 'gte' branch to fail
        failures = check_donor_eligibility(branch_no_ruleset, data)
        # Should fail with WEIGHT, not raise TypeError
        assert 'WEIGHT' in _rule_codes(failures)


# ─── get_required_tests() ─────────────────────────────────────────────────────

class TestGetRequiredTests:

    def test_no_ruleset_returns_four_defaults(self, db, branch_no_ruleset):
        from compliance.engine import get_required_tests
        tests = get_required_tests(branch_no_ruleset)
        assert set(tests) == {'HIV_AgAb', 'HBsAg', 'anti_HCV', 'syphilis'}

    def test_ruleset_with_required_tests_returns_them(self, db):
        from decimal import Decimal
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset, ComplianceRule
        from core.models import Branch
        from tests.conftest import UserFactory

        jur = ComplianceJurisdiction.objects.create(name='Test', country_code='TT')
        user = UserFactory()
        ruleset = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='draft',
            created_by=user,
        )
        ComplianceRule.objects.create(
            ruleset=ruleset, rule_kind='REQUIRED_TEST',
            applies_to='donor_eligibility',
            operator='required',
            citation='HIV_NAT',
            threshold_unit='',
        )
        ComplianceRule.objects.create(
            ruleset=ruleset, rule_kind='REQUIRED_TEST',
            applies_to='donor_eligibility',
            operator='required',
            citation='HBsAg',
            threshold_unit='',
        )
        branch = Branch.objects.create(
            name='Test Branch RT', facility_code='TRT',
            active_ruleset=ruleset,
        )
        from compliance.engine import get_required_tests
        tests = get_required_tests(branch)
        assert 'HIV_NAT' in tests
        assert 'HBsAg' in tests

    def test_ruleset_with_no_required_test_rules_falls_back_to_defaults(self, db):
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset
        from core.models import Branch
        from tests.conftest import UserFactory

        jur = ComplianceJurisdiction.objects.create(name='Test2', country_code='T2')
        user = UserFactory()
        ruleset = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='draft',
            created_by=user,
        )
        branch = Branch.objects.create(
            name='Test Branch NR', facility_code='TNR',
            active_ruleset=ruleset,
        )
        from compliance.engine import get_required_tests
        tests = get_required_tests(branch)
        assert set(tests) == {'HIV_AgAb', 'HBsAg', 'anti_HCV', 'syphilis'}


# ─── DB-ruleset path ──────────────────────────────────────────────────────────

@pytest.fixture
def branch_with_ruleset(db):
    """Branch with a live ComplianceRuleset (draft status — not locked)."""
    from decimal import Decimal
    from django.utils import timezone
    from compliance.models import ComplianceJurisdiction, ComplianceRuleset, ComplianceRule
    from core.models import Branch
    from tests.conftest import UserFactory

    jur = ComplianceJurisdiction.objects.create(name='WHO Global', country_code='XW')
    user = UserFactory()
    ruleset = ComplianceRuleset.objects.create(
        jurisdiction=jur, version='1.0',
        effective_from=timezone.now().date(),
        status='draft',
        created_by=user,
    )
    # Minimum set: AGE and WEIGHT only (so tests don't need all 7 values)
    ComplianceRule.objects.create(
        ruleset=ruleset, rule_kind='AGE', applies_to='donor_eligibility',
        operator='between',
        threshold_value=Decimal('18'), threshold_value_2=Decimal('65'),
        threshold_unit='years', citation='WHO §3.1',
    )
    ComplianceRule.objects.create(
        ruleset=ruleset, rule_kind='WEIGHT', applies_to='donor_eligibility',
        operator='gte',
        threshold_value=Decimal('50'), threshold_value_2=None,
        threshold_unit='kg', citation='WHO §3.2',
    )
    branch = Branch.objects.create(
        name='DB Ruleset Branch', facility_code='DBR',
        active_ruleset=ruleset,
    )
    return branch


class TestDBRulesetPath:

    def test_passing_data_with_db_ruleset(self, db, branch_with_ruleset):
        data = {'age': 30, 'weight_kg': 70, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch_with_ruleset, data)
        assert failures == []

    def test_age_failure_via_db_ruleset(self, db, branch_with_ruleset):
        data = {'age': 17, 'weight_kg': 70, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch_with_ruleset, data)
        assert 'AGE' in _rule_codes(failures)

    def test_weight_failure_via_db_ruleset(self, db, branch_with_ruleset):
        data = {'age': 30, 'weight_kg': 45, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch_with_ruleset, data)
        assert 'WEIGHT' in _rule_codes(failures)

    def test_db_ruleset_failure_has_citation(self, db, branch_with_ruleset):
        data = {'age': 30, 'weight_kg': 45, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch_with_ruleset, data)
        weight_f = next(f for f in failures if f.rule_kind == 'WEIGHT')
        assert weight_f.citation == 'WHO §3.2'

    def test_db_ruleset_skips_hardcoded_minimums(self, db, branch_with_ruleset):
        """When a ruleset is configured, hardcoded minimums should NOT apply.
        E.g. HB is not in the ruleset, so it should never fail."""
        data = {
            'age': 30, 'weight_kg': 70,
            'hb_g_dl': 10.0,  # Would fail hardcoded HB minimum
            'deferral_status': 'active', 'sex': 'M',
        }
        failures = check_donor_eligibility(branch_with_ruleset, data)
        assert 'HB' not in _rule_codes(failures)


# ─── Individual operators via DB ruleset ─────────────────────────────────────

@pytest.fixture
def _make_rule_branch(db):
    """Factory that creates a branch with one custom rule and returns (branch, rule)."""
    from decimal import Decimal
    from django.utils import timezone
    from compliance.models import ComplianceJurisdiction, ComplianceRuleset, ComplianceRule
    from core.models import Branch
    from tests.conftest import UserFactory

    _counter = [0]

    def factory(rule_kind, operator, threshold, threshold2=None, predicate=None):
        _counter[0] += 1
        cc = f'X{_counter[0]}'[:2]
        jur, _ = ComplianceJurisdiction.objects.get_or_create(
            country_code=cc, defaults={'name': f'Jur {cc}'}
        )
        user = UserFactory()
        ruleset = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='draft', created_by=user,
        )
        rule = ComplianceRule.objects.create(
            ruleset=ruleset, rule_kind=rule_kind,
            applies_to='donor_eligibility',
            operator=operator,
            threshold_value=Decimal(str(threshold)) if threshold is not None else None,
            threshold_value_2=Decimal(str(threshold2)) if threshold2 is not None else None,
            threshold_unit='units', citation=f'{rule_kind} test citation',
            applies_predicate=predicate,
        )
        branch = Branch.objects.create(
            name=f'Rule Branch {_counter[0]}',
            facility_code=f'R{_counter[0]:02d}',
            active_ruleset=ruleset,
        )
        return branch, rule

    return factory


class TestOperators:

    def test_gt_operator_fails_when_value_not_greater(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('PULSE', 'gt', 60)
        # Value == threshold → should FAIL (must be strictly greater)
        data = {'pulse': 60, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'PULSE' in _rule_codes(failures)

    def test_gt_operator_passes_when_strictly_greater(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('PULSE', 'gt', 60)
        data = {'pulse': 61, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'PULSE' not in _rule_codes(failures)

    def test_lt_operator_fails_when_value_not_less(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('PULSE', 'lt', 100)
        # Value == threshold → should FAIL (must be strictly less)
        data = {'pulse': 100, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'PULSE' in _rule_codes(failures)

    def test_lt_operator_passes_when_strictly_less(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('PULSE', 'lt', 100)
        data = {'pulse': 99, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'PULSE' not in _rule_codes(failures)

    def test_eq_operator_passes_on_exact_match(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('AGE', 'eq', 18)
        data = {'age': 18, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'AGE' not in _rule_codes(failures)

    def test_eq_operator_fails_on_mismatch(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('AGE', 'eq', 18)
        data = {'age': 19, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'AGE' in _rule_codes(failures)

    def test_lte_operator_passes_at_boundary(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('AGE', 'lte', 65)
        data = {'age': 65, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'AGE' not in _rule_codes(failures)

    def test_lte_operator_fails_above_boundary(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('AGE', 'lte', 65)
        data = {'age': 66, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'AGE' in _rule_codes(failures)

    def test_gte_operator_passes_at_boundary(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('WEIGHT', 'gte', 50)
        data = {'weight_kg': 50, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'WEIGHT' not in _rule_codes(failures)

    def test_gte_operator_fails_below_boundary(self, db, _make_rule_branch):
        branch, _ = _make_rule_branch('WEIGHT', 'gte', 50)
        data = {'weight_kg': 49, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'WEIGHT' in _rule_codes(failures)

    def test_required_operator_passes_when_value_truthy(self, db, _make_rule_branch):
        """'required' operator: rule PASSES (no failure) when value is truthy."""
        branch, _ = _make_rule_branch('HB', 'required', 0)
        # HB = 12.5 is truthy → rule passes
        data = {'hb_g_dl': 12.5, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'HB' not in _rule_codes(failures)

    def test_required_operator_fails_when_value_zero(self, db, _make_rule_branch):
        """'required' operator: rule FAILS when value evaluates to falsy (e.g. 0)."""
        branch, _ = _make_rule_branch('HB', 'required', 0)
        data = {'hb_g_dl': 0, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'HB' in _rule_codes(failures)

    def test_forbidden_operator_passes_when_value_falsy(self, db, _make_rule_branch):
        """'forbidden' operator: rule PASSES (no failure) when value is falsy (0 or None)."""
        branch, _ = _make_rule_branch('HB', 'forbidden', 0)
        # HB = 0 is falsy → 'forbidden' rule passes (no failure)
        data = {'hb_g_dl': 0, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'HB' not in _rule_codes(failures)

    def test_forbidden_operator_fails_when_value_truthy(self, db, _make_rule_branch):
        """'forbidden' operator: rule FAILS when value is truthy (something is present that shouldn't be)."""
        branch, _ = _make_rule_branch('HB', 'forbidden', 0)
        data = {'hb_g_dl': 12.5, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'HB' in _rule_codes(failures)

    def test_unknown_operator_defaults_to_pass(self, db, _make_rule_branch):
        """An unrecognised operator must not crash — the engine defaults to passing."""
        from decimal import Decimal
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset, ComplianceRule
        from core.models import Branch
        from tests.conftest import UserFactory
        jur, _ = ComplianceJurisdiction.objects.get_or_create(
            country_code='UK', defaults={'name': 'Unknown Op Test'}
        )
        user = UserFactory()
        ruleset = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='draft', created_by=user,
        )
        ComplianceRule.objects.create(
            ruleset=ruleset, rule_kind='AGE',
            applies_to='donor_eligibility',
            operator='not_a_real_operator',
            threshold_value=Decimal('18'),
            threshold_unit='years', citation='test',
        )
        branch = Branch.objects.create(
            name='Unknown Op Branch', facility_code='UOP',
            active_ruleset=ruleset,
        )
        data = {'age': 10, 'deferral_status': 'active'}
        failures = check_donor_eligibility(branch, data)
        assert 'AGE' not in _rule_codes(failures)


# ─── applies_predicate filtering ─────────────────────────────────────────────

class TestAppliesPredicate:

    def test_sex_predicate_skips_rule_for_different_sex(self, db, _make_rule_branch):
        """A rule with applies_predicate={"sex": "F"} must not fire for male donors."""
        branch, _ = _make_rule_branch('HB', 'gte', 13.5, predicate={'sex': 'F'})
        data = {'hb_g_dl': 12.5, 'deferral_status': 'active', 'sex': 'M'}
        failures = check_donor_eligibility(branch, data)
        assert 'HB' not in _rule_codes(failures)

    def test_sex_predicate_applies_for_matching_sex(self, db, _make_rule_branch):
        """A rule with applies_predicate={"sex": "F"} MUST fire for female donors."""
        branch, _ = _make_rule_branch('HB', 'gte', 13.5, predicate={'sex': 'F'})
        data = {'hb_g_dl': 12.5, 'deferral_status': 'active', 'sex': 'F'}
        failures = check_donor_eligibility(branch, data)
        assert 'HB' in _rule_codes(failures)

    def test_null_predicate_always_applies(self, db, _make_rule_branch):
        """A rule with no predicate applies regardless of sex."""
        branch, _ = _make_rule_branch('WEIGHT', 'gte', 60, predicate=None)
        data = {'weight_kg': 55, 'deferral_status': 'active', 'sex': 'F'}
        failures = check_donor_eligibility(branch, data)
        assert 'WEIGHT' in _rule_codes(failures)


# ─── ComplianceRuleset lock behaviour ────────────────────────────────────────

class TestRulesetLocking:

    def test_setting_status_active_locks_ruleset(self, db):
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset
        from tests.conftest import UserFactory

        jur = ComplianceJurisdiction.objects.create(name='Lock Test', country_code='LK')
        user = UserFactory()
        rs = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='draft', created_by=user,
        )
        assert not rs.locked
        rs.status = 'active'
        rs.save()
        rs.refresh_from_db()
        assert rs.locked

    def test_modifying_locked_ruleset_raises_value_error(self, db):
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset
        from tests.conftest import UserFactory
        import pytest

        jur = ComplianceJurisdiction.objects.create(name='Lock Test2', country_code='L2')
        user = UserFactory()
        rs = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='active', created_by=user,
        )
        rs.refresh_from_db()
        assert rs.locked
        rs.version = '2.0'
        with pytest.raises(ValueError, match='locked'):
            rs.save()

    def test_locked_ruleset_allows_status_transition_to_superseded(self, db):
        """A locked (active) ruleset must still be transitionable to superseded.

        Regression: save() previously raised on ANY save of a locked row,
        blocking the version-supersede workflow it was meant to permit.
        """
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset
        from tests.conftest import UserFactory

        jur = ComplianceJurisdiction.objects.create(name='Lock Test3', country_code='L3')
        user = UserFactory()
        rs = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='active', created_by=user,
        )
        rs.refresh_from_db()
        assert rs.locked

        # Superseding is a lifecycle transition — must be allowed.
        rs.status = 'superseded'
        rs.effective_to = timezone.now().date()
        rs.save()  # must not raise
        rs.refresh_from_db()
        assert rs.status == 'superseded'

    def test_locked_ruleset_still_blocks_content_edit_after_transition(self, db):
        """Even mixed with an allowed field change, a disallowed edit is rejected."""
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset
        from tests.conftest import UserFactory
        import pytest

        jur = ComplianceJurisdiction.objects.create(name='Lock Test4', country_code='L4')
        user = UserFactory()
        rs = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='active', created_by=user,
        )
        rs.refresh_from_db()
        # status is allowed, but version is not — presence of a disallowed
        # field must still abort the save.
        rs.status = 'superseded'
        rs.version = '9.9'
        with pytest.raises(ValueError, match='locked'):
            rs.save()


# ─── Property-based boundary tests (Hypothesis) ──────────────────────────────

try:
    from hypothesis import given, settings as hyp_settings, HealthCheck
    from hypothesis import strategies as st
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False

if HYPOTHESIS_AVAILABLE:

    @pytest.mark.django_db
    class TestHypothesisBoundaries:
        """Property-based tests: any value strictly outside the valid range must fail."""

        @given(age=st.integers(min_value=0, max_value=17))
        @hyp_settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_underage_always_fails(self, db, age):
            from core.models import Branch
            branch = Branch.objects.create(
                name=f'HypBranch-age-{age}', facility_code=f'H{age % 26:02d}'
            )
            data = _passing_donor_data()
            data['age'] = age
            failures = check_donor_eligibility(branch, data)
            assert 'AGE' in _rule_codes(failures)

        @given(age=st.integers(min_value=66, max_value=120))
        @hyp_settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_overage_always_fails(self, db, age):
            from core.models import Branch
            branch = Branch.objects.create(
                name=f'HypBranch-ov-{age}', facility_code=f'V{age % 26:02d}'
            )
            data = _passing_donor_data()
            data['age'] = age
            failures = check_donor_eligibility(branch, data)
            assert 'AGE' in _rule_codes(failures)

        @given(weight=st.integers(min_value=1, max_value=49))
        @hyp_settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_underweight_always_fails(self, db, weight):
            from core.models import Branch
            branch = Branch.objects.create(
                name=f'HypBranch-wt-{weight}', facility_code=f'W{weight % 26:02d}'
            )
            data = _passing_donor_data()
            data['weight_kg'] = weight
            failures = check_donor_eligibility(branch, data)
            assert 'WEIGHT' in _rule_codes(failures)

        @given(hb=st.floats(min_value=1.0, max_value=12.49))
        @hyp_settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_low_haemoglobin_always_fails(self, db, hb):
            from core.models import Branch
            import math
            if math.isnan(hb) or math.isinf(hb):
                return
            branch = Branch.objects.create(
                name=f'HypBranch-hb-{int(hb*10)}', facility_code='HB'
            )
            data = _passing_donor_data()
            data['hb_g_dl'] = hb
            failures = check_donor_eligibility(branch, data)
            assert 'HB' in _rule_codes(failures)

        @given(pulse=st.integers(min_value=1, max_value=59))
        @hyp_settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
        def test_low_pulse_always_fails(self, db, pulse):
            from core.models import Branch
            branch = Branch.objects.create(
                name=f'HypBranch-pl-{pulse}', facility_code=f'P{pulse % 26:02d}'
            )
            data = _passing_donor_data()
            data['pulse'] = pulse
            failures = check_donor_eligibility(branch, data)
            assert 'PULSE' in _rule_codes(failures)


# ─── Compliance engine edge cases ────────────────────────────────────────────

class TestComplianceEngineEdgeCases:
    """
    Edge cases that must not raise exceptions:
      - NaN/Inf float values in donor data
      - Unparseable (non-numeric) values
      - Missing keys
    """

    @pytest.mark.django_db
    def test_nan_hb_does_not_crash(self, db, branch):
        """float('nan') must not cause Decimal('NaN') InvalidOperation."""
        data = _passing_donor_data()
        data['hb_g_dl'] = float('nan')
        failures = check_donor_eligibility(branch, data)
        # Passes or fails — what matters is no exception is raised
        assert isinstance(failures, list)

    @pytest.mark.django_db
    def test_inf_weight_does_not_crash(self, db, branch):
        """float('inf') must not cause a comparison error."""
        data = _passing_donor_data()
        data['weight_kg'] = float('inf')
        failures = check_donor_eligibility(branch, data)
        assert isinstance(failures, list)

    @pytest.mark.django_db
    def test_negative_inf_weight_does_not_crash(self, db, branch):
        """float('-inf') must not cause a comparison error."""
        data = _passing_donor_data()
        data['weight_kg'] = float('-inf')
        failures = check_donor_eligibility(branch, data)
        assert isinstance(failures, list)

    @pytest.mark.django_db
    def test_string_value_in_numeric_field_does_not_crash(self, db, branch):
        """A string in a numeric field must not crash — just skip that rule."""
        data = _passing_donor_data()
        data['age'] = 'not_a_number'
        failures = check_donor_eligibility(branch, data)
        assert isinstance(failures, list)

    @pytest.mark.django_db
    def test_missing_all_keys_returns_empty_failures(self, db, branch):
        """When all numeric keys are missing, no rule fires (all values are None)."""
        data = {'deferral_status': 'active'}
        failures = check_donor_eligibility(branch, data)
        # No values provided — nothing to evaluate
        assert isinstance(failures, list)

    @pytest.mark.django_db
    def test_deferred_donor_always_fails_regardless_of_vitals(self, db, branch):
        """A permanently deferred donor must fail even with perfect vitals."""
        data = _passing_donor_data()
        data['deferral_status'] = 'permanent_defer'
        failures = check_donor_eligibility(branch, data)
        codes = _rule_codes(failures)
        assert 'DEFERRAL' in codes

    @pytest.mark.django_db
    def test_between_operator_with_null_t2_does_not_crash(self, db):
        """
        Regression: 'between' operator with threshold_value_2=None in a DB rule
        would cause TypeError (t <= v <= None). After fix, falls back to v >= t.
        """
        from decimal import Decimal
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset, ComplianceRule
        from core.models import Branch
        from tests.conftest import UserFactory

        jur, _ = ComplianceJurisdiction.objects.get_or_create(
            country_code='BT', defaults={'name': 'Between-T2-None Test'}
        )
        user = UserFactory()
        ruleset = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='draft', created_by=user,
        )
        ComplianceRule.objects.create(
            ruleset=ruleset, rule_kind='AGE',
            applies_to='donor_eligibility',
            operator='between',
            threshold_value=Decimal('18'),
            threshold_value_2=None,   # <-- misconfigured: t2 is None
            threshold_unit='years',
            citation='Test',
        )
        branch = Branch.objects.create(
            name='Between T2 None Branch', facility_code='BTN',
            active_ruleset=ruleset,
        )
        data = {'age': 17, 'deferral_status': 'active'}
        # Must not raise TypeError — should evaluate as age >= 18 fallback
        failures = check_donor_eligibility(branch, data)
        assert isinstance(failures, list)
        # Value 17 is below threshold 18, so rule should fire
        assert 'AGE' in _rule_codes(failures)

    @pytest.mark.django_db
    def test_between_operator_with_valid_t2_enforces_upper_bound(self, db):
        """'between' with both t and t2 set must enforce the upper bound."""
        from decimal import Decimal
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset, ComplianceRule
        from core.models import Branch
        from tests.conftest import UserFactory

        jur, _ = ComplianceJurisdiction.objects.get_or_create(
            country_code='BU', defaults={'name': 'Between Upper Bound'}
        )
        user = UserFactory()
        ruleset = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.1',
            effective_from=timezone.now().date(),
            status='draft', created_by=user,
        )
        ComplianceRule.objects.create(
            ruleset=ruleset, rule_kind='AGE',
            applies_to='donor_eligibility',
            operator='between',
            threshold_value=Decimal('18'),
            threshold_value_2=Decimal('65'),
            threshold_unit='years', citation='WHO §3.1',
        )
        branch = Branch.objects.create(
            name='Between Upper Branch', facility_code='BUB',
            active_ruleset=ruleset,
        )
        # Above upper bound — must fail
        data_old = {'age': 70, 'deferral_status': 'active'}
        assert 'AGE' in _rule_codes(check_donor_eligibility(branch, data_old))
        # Within bounds — must pass
        data_ok = {'age': 30, 'deferral_status': 'active'}
        assert 'AGE' not in _rule_codes(check_donor_eligibility(branch, data_ok))

    @pytest.mark.django_db
    def test_null_threshold_value_for_comparison_operator_does_not_crash(self, db):
        """
        Regression: operators like 'gt'/'gte' with threshold_value=None would
        cause TypeError (v > None) in _evaluate_rule.
        After fix, the rule is skipped silently when t is None.
        """
        from decimal import Decimal
        from django.utils import timezone
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset, ComplianceRule
        from core.models import Branch
        from tests.conftest import UserFactory

        jur, _ = ComplianceJurisdiction.objects.get_or_create(
            country_code='NT', defaults={'name': 'Null Threshold Test'}
        )
        user = UserFactory()
        ruleset = ComplianceRuleset.objects.create(
            jurisdiction=jur, version='1.0',
            effective_from=timezone.now().date(),
            status='draft', created_by=user,
        )
        ComplianceRule.objects.create(
            ruleset=ruleset, rule_kind='AGE',
            applies_to='donor_eligibility',
            operator='gte',
            threshold_value=None,   # <-- misconfigured: no threshold
            threshold_unit='years', citation='test',
        )
        branch = Branch.objects.create(
            name='Null Threshold Branch', facility_code='NTB',
            active_ruleset=ruleset,
        )
        data = {'age': 17, 'deferral_status': 'active'}
        # Must not raise TypeError — misconfigured rule should be silently skipped
        failures = check_donor_eligibility(branch, data)
        assert isinstance(failures, list)
        # Rule skipped: no AGE failure despite age being 17
        assert 'AGE' not in _rule_codes(failures)
