"""
State machine tests — valid and invalid transitions.
Run: pytest tests/test_state_machine.py -v
"""
import pytest
from django.core.exceptions import ValidationError

from tests.conftest import BloodUnitFactory, BranchFactory, UserFactory, DonationFactory, DonorFactory


class TestValidTransitions:

    def test_quarantined_to_in_testing(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='quarantined', owner_branch=branch)
        transition_unit(unit, 'in_testing', actor=user, reason='TTI batch')
        unit.refresh_from_db()
        assert unit.status == 'in_testing'

    def test_in_testing_to_available(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='in_testing', owner_branch=branch)
        transition_unit(unit, 'available', actor=user, reason='TTI clear')
        unit.refresh_from_db()
        assert unit.status == 'available'

    def test_available_to_reserved(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        transition_unit(unit, 'reserved', actor=user, reason='XM lock')
        unit.refresh_from_db()
        assert unit.status == 'reserved'

    def test_reserved_to_crossmatched(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='reserved', owner_branch=branch)
        transition_unit(unit, 'crossmatched', actor=user, reason='XM complete')
        unit.refresh_from_db()
        assert unit.status == 'crossmatched'

    def test_status_event_created_on_transition(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        from inventory.models import UnitStatusEvent
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='quarantined', owner_branch=branch)
        transition_unit(unit, 'in_testing', actor=user, reason='test')
        assert UnitStatusEvent.objects.filter(
            unit=unit, from_status='quarantined', to_status='in_testing'
        ).exists()


class TestInvalidTransitions:

    def test_issued_cannot_go_back_to_available(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        from django.core.exceptions import ValidationError
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='issued', owner_branch=branch)
        with pytest.raises(ValidationError):
            transition_unit(unit, 'available', actor=user, reason='oops')

    def test_transfused_cannot_go_to_any_active_state(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        from django.core.exceptions import ValidationError
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        for target in ('available', 'reserved', 'crossmatched', 'issued', 'in_testing'):
            unit = BloodUnitFactory(donation=donation, status='transfused', owner_branch=branch)
            with pytest.raises(ValidationError, match=''):
                transition_unit(unit, target, actor=user, reason='illegal')

    def test_destroyed_cannot_transition_anywhere(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        from django.core.exceptions import ValidationError
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        for target in ('available', 'quarantined', 'in_testing'):
            unit = BloodUnitFactory(donation=donation, status='destroyed', owner_branch=branch)
            with pytest.raises(ValidationError):
                transition_unit(unit, target, actor=user, reason='illegal')


class TestNonIssuableStates:

    @pytest.mark.parametrize('bad_status', [
        'quarantined', 'in_testing', 'failed_qc', 'expired',
        'recalled', 'quarantined_holdback', 'wasted', 'destroyed',
        'transferred_out', 'in_transit',
    ])
    def test_non_issuable_status_in_set(self, bad_status):
        from inventory.state_machine import _NON_ISSUABLE
        assert bad_status in _NON_ISSUABLE, \
            f"'{bad_status}' should be in _NON_ISSUABLE"


class TestAlwaysAllowedTransitions:
    """_ALWAYS_ALLOWED_TO states (recall, quarantine, expire, destroy) must
    be reachable from any non-terminal state."""

    def test_available_can_always_be_recalled(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='available', owner_branch=branch)
        transition_unit(unit, 'recalled', actor=user, reason='Lookback recall')
        unit.refresh_from_db()
        assert unit.status == 'recalled'

    def test_reserved_can_be_quarantined_holdback(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='reserved', owner_branch=branch)
        transition_unit(unit, 'quarantined_holdback', actor=user, reason='Excursion auto-quarantine')
        unit.refresh_from_db()
        assert unit.status == 'quarantined_holdback'

    def test_issued_can_be_expired(self, db, branch, user, donor):
        from inventory.state_machine import transition_unit, seed_transitions
        seed_transitions()
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        unit = BloodUnitFactory(donation=donation, status='issued', owner_branch=branch)
        transition_unit(unit, 'expired', actor=user, reason='Cron job: unit expired before transfusion recorded')
        unit.refresh_from_db()
        assert unit.status == 'expired'


class TestCanTransition:
    """Unit tests for the can_transition() helper."""

    def test_destroyed_is_terminal(self):
        from inventory.state_machine import can_transition
        allowed, msg = can_transition('destroyed', 'available')
        assert not allowed
        assert 'terminal' in msg.lower()

    def test_always_allowed_to_recalled(self):
        from inventory.state_machine import can_transition
        allowed, _ = can_transition('issued', 'recalled')
        assert allowed

    def test_impossible_transition_returns_false(self, db, branch):
        from inventory.state_machine import can_transition, seed_transitions
        seed_transitions()
        allowed, msg = can_transition('transfused', 'available')
        assert not allowed
        assert 'not permitted' in msg.lower() or 'terminal' in msg.lower()
