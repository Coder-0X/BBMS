"""
Compliance rule engine.

Evaluates a donor or unit against the active ruleset for a branch.
Returns a list of failures — empty list means all rules passed.
"""
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from .models import ComplianceRule


@dataclass
class RuleFailure:
    rule_kind: str
    message: str
    citation: str


def _predicate_matches(predicate: dict | None, context: dict) -> bool:
    """Check that all predicate conditions are met by the context dict."""
    if not predicate:
        return True
    return all(context.get(k) == v for k, v in predicate.items())


def _evaluate_rule(rule: ComplianceRule, value, context: dict) -> RuleFailure | None:
    if value is None:
        return None
    if not _predicate_matches(rule.applies_predicate, context):
        return None

    # Reject NaN/Inf floats — they cannot be meaningfully compared
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None

    try:
        v = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None  # Unparseable value — skip this rule silently
    t = rule.threshold_value
    t2 = rule.threshold_value_2

    # Guard: comparison operators need at least t; skip if misconfigured
    if t is None and rule.operator not in ('required', 'forbidden'):
        return None

    passed = {
        'gt':  lambda: v > t,
        'lt':  lambda: v < t,
        'gte': lambda: v >= t,
        'lte': lambda: v <= t,
        'eq':  lambda: v == t,
        'between': lambda: (t <= v <= t2) if t2 is not None else v >= t,
        'required': lambda: bool(value),
        'forbidden': lambda: not bool(value),
    }.get(rule.operator, lambda: True)()

    if not passed:
        msg = (
            f"{rule.get_rule_kind_display()} must be "
            f"{rule.get_operator_display()} {t}"
            f"{' and ' + str(t2) if t2 else ''} {rule.threshold_unit}".strip()
        )
        return RuleFailure(rule.rule_kind, msg, rule.citation)
    return None


_HARDCODED_MINIMUMS = [
    # (rule_kind, operator, threshold, threshold2, unit, citation)
    ('AGE',               'between', Decimal('18'), Decimal('65'),  'years',  'WHO Blood Donor Selection Guidelines §3.1'),
    ('WEIGHT',            'gte',     Decimal('50'), None,           'kg',     'WHO §3.2'),
    ('HB',                'gte',     Decimal('12.5'), None,         'g/dL',   'WHO §3.3 (12.5 g/dL minimum)'),
    ('BP_SYSTOLIC',       'between', Decimal('100'), Decimal('180'),'mmHg',   'AABB Standards 2024 §5.6'),
    ('BP_DIASTOLIC',      'between', Decimal('60'),  Decimal('100'),'mmHg',   'AABB Standards 2024 §5.6'),
    ('PULSE',             'between', Decimal('60'),  Decimal('100'),'bpm',    'AABB Standards 2024 §5.6'),
    ('DONATION_INTERVAL', 'gte',     Decimal('56'),  None,          'days',   'WHO §3.4 (56-day minimum interval)'),
]


def _apply_hardcoded_minimums(donor_data: dict) -> list[RuleFailure]:
    """Apply WHO/AABB minimum rules when no branch ruleset is configured."""
    VALUE_MAP = {
        'AGE': donor_data.get('age'),
        'WEIGHT': donor_data.get('weight_kg'),
        'HB': donor_data.get('hb_g_dl'),
        'BP_SYSTOLIC': donor_data.get('bp_systolic'),
        'BP_DIASTOLIC': donor_data.get('bp_diastolic'),
        'PULSE': donor_data.get('pulse'),
        'DONATION_INTERVAL': donor_data.get('days_since_last_donation'),
    }
    failures = []
    for rule_kind, op, t, t2, unit, citation in _HARDCODED_MINIMUMS:
        value = VALUE_MAP.get(rule_kind)
        if value is None:
            continue
        # Reject NaN/Inf floats before Decimal conversion
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            continue
        try:
            v = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        passed = {
            'gte':     lambda: v >= t,
            'lte':     lambda: v <= t,
            'between': lambda: t <= v <= t2,
        }.get(op, lambda: True)()
        if not passed:
            label = {
                'AGE': 'Age', 'WEIGHT': 'Weight', 'HB': 'Haemoglobin',
                'BP_SYSTOLIC': 'Systolic BP', 'BP_DIASTOLIC': 'Diastolic BP',
                'PULSE': 'Pulse', 'DONATION_INTERVAL': 'Donation interval',
            }.get(rule_kind, rule_kind)
            msg = (
                f"{label} must be "
                f"{'between ' + str(t) + ' and ' + str(t2) if op == 'between' else '>= ' + str(t)} "
                f"{unit}"
            )
            failures.append(RuleFailure(rule_kind, msg, citation))
    return failures


def check_donor_eligibility(branch, donor_data: dict) -> list[RuleFailure]:
    """
    donor_data keys: age, weight_kg, hb_g_dl, bp_systolic, bp_diastolic,
                     pulse, days_since_last_donation, sex
    Returns a list of failures (empty = eligible).
    """
    # Deferral check always runs regardless of ruleset
    failures = []
    if donor_data.get('deferral_status') in ('temporary_defer', 'permanent_defer'):
        failures.append(RuleFailure(
            'DEFERRAL',
            f"Donor is {donor_data['deferral_status'].replace('_', ' ')} — donation blocked.",
            'Local deferral policy',
        ))

    ruleset = branch.active_ruleset
    if not ruleset:
        failures.extend(_apply_hardcoded_minimums(donor_data))
        return failures

    rules = ruleset.rules.filter(applies_to='donor_eligibility')
    VALUE_MAP = {
        'AGE': donor_data.get('age'),
        'WEIGHT': donor_data.get('weight_kg'),
        'HB': donor_data.get('hb_g_dl'),
        'BP_SYSTOLIC': donor_data.get('bp_systolic'),
        'BP_DIASTOLIC': donor_data.get('bp_diastolic'),
        'PULSE': donor_data.get('pulse'),
        'DONATION_INTERVAL': donor_data.get('days_since_last_donation'),
        'MAX_VOLUME': donor_data.get('volume_ml'),
    }

    for rule in rules:
        value = VALUE_MAP.get(rule.rule_kind)
        failure = _evaluate_rule(rule, value, donor_data)
        if failure:
            failures.append(failure)
    return failures


def get_required_tests(branch) -> list[str]:
    """Return the list of test codes required for donations at this branch."""
    ruleset = branch.active_ruleset
    if not ruleset:
        # Fall back to the global minimum
        return ['HIV_AgAb', 'HBsAg', 'anti_HCV', 'syphilis']

    rules = ruleset.rules.filter(rule_kind='REQUIRED_TEST', operator='required')
    return [r.citation for r in rules] or ['HIV_AgAb', 'HBsAg', 'anti_HCV', 'syphilis']
