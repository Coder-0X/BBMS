"""
Blood unit state machine.

Call transition_unit() everywhere you need to change a unit's status.
It checks the allowed transitions table, writes a UnitStatusEvent,
bumps the version counter, and writes to the audit log.
"""
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError


# These transitions are always allowed regardless of the UnitStateTransition table.
# They represent emergency/exception paths that override normal flow.
_ALWAYS_ALLOWED_TO = {'recalled', 'quarantined_holdback', 'expired', 'destroyed'}

# Terminal states — nothing leaves these except destroyed
_TERMINAL = {'destroyed'}

# States that can never be issued — enforced here AND in the issue flow
_NON_ISSUABLE = {
    'quarantined', 'in_testing', 'failed_qc', 'expired',
    'recalled', 'quarantined_holdback', 'wasted', 'transferred_out',
    'in_transit', 'destroyed',
}


def can_transition(from_status: str, to_status: str) -> tuple[bool, str]:
    """
    Check if a status change is allowed without doing it.
    Returns (allowed, reason_if_not).
    """
    if from_status in _TERMINAL:
        return False, f"Unit is in terminal state '{from_status}' and cannot be changed."

    if to_status in _ALWAYS_ALLOWED_TO:
        return True, ""

    from .models import UnitStateTransition
    allowed = UnitStateTransition.objects.filter(
        from_status=from_status, to_status=to_status
    ).exists()

    if not allowed:
        return False, f"Transition '{from_status}' → '{to_status}' is not permitted."

    return True, ""


@transaction.atomic
def transition_unit(unit, new_status: str, actor, reason: str = '', esign=None):
    """
    Transition a blood unit to a new status.
    Must be called inside an existing transaction (or will create one).
    """
    from .models import UnitStatusEvent
    from audit.utils import write_audit

    old_status = unit.status
    allowed, msg = can_transition(old_status, new_status)
    if not allowed:
        raise ValidationError(msg)

    # Write the event record first (append-only)
    UnitStatusEvent.objects.create(
        unit=unit,
        from_status=old_status,
        to_status=new_status,
        reason=reason,
        actor=actor,
        esign=esign,
        occurred_at=timezone.now(),
    )

    unit.status = new_status
    unit.version += 1
    unit.save(update_fields=['status', 'version'])

    write_audit(
        actor=actor,
        action='unit.status_changed',
        entity_table='inventory_bloodunit',
        entity_id=unit.pk,
        before={'status': old_status},
        after={'status': new_status},
        action_meaning=f"{unit.did}: {old_status} → {new_status}. {reason}".strip(),
        branch=unit.owner_branch,
    )


def seed_transitions():
    """
    Populate the UnitStateTransition table with all allowed moves.
    Call this once after migrations via: python manage.py shell -c "from inventory.state_machine import seed_transitions; seed_transitions()"
    """
    from .models import UnitStateTransition

    allowed = [
        # Normal flow
        ('quarantined',        'in_testing',          'test.perform',   ''),
        ('in_testing',         'available',            'unit.release',   'All TTI tests non-reactive and e-signed'),
        ('in_testing',         'failed_qc',            'unit.release',   ''),
        ('available',          'reserved',             'unit.reserve',   ''),
        ('available',          'crossmatched',         'test.crossmatch','Direct crossmatch without reservation step'),
        ('available',          'transferred_out',      'transfer.send',  ''),
        ('reserved',           'available',            'unit.reserve',   'Reservation released or expired'),
        ('reserved',           'crossmatched',         'test.crossmatch',''),
        ('crossmatched',       'issued',               'unit.release',   'SELECT FOR UPDATE enforced in issue flow'),
        ('crossmatched',       'reserved',             'test.crossmatch','Crossmatch cancelled'),
        ('crossmatched',       'available',            'unit.reserve',   'Crossmatch cancelled and reservation released'),
        ('issued',             'transfused',           'transfusion.record', ''),
        ('issued',             'returned_to_stock',    'transfusion.record', 'Within 30 min / validated temp'),
        ('issued',             'wasted',               'transfusion.record', ''),
        ('available',          'wasted',               'unit.dispose',   'Damaged / temp excursion before issue'),
        ('reserved',           'wasted',               'unit.dispose',   'Damaged while reserved'),
        ('crossmatched',       'wasted',               'unit.dispose',   'Damaged while crossmatched'),
        ('returned_to_stock',  'wasted',               'unit.dispose',   'Rejected on return'),
        ('returned_to_stock',  'reserved',             'unit.reserve',   ''),
        ('returned_to_stock',  'available',            '',               ''),
        ('transferred_out',    'in_transit',           'transfer.send',  ''),
        ('transferred_out',    'available',            'transfer.reject', 'Transfer rejected or cancelled before dispatch'),
        ('available',          'issued',               'processing.pool', 'PLT unit consumed in platelet pooling operation'),
        ('in_transit',         'available',            'transfer.receive','Received at destination'),
        ('in_transit',         'returned_to_stock',    'transfer.receive',''),
        # Anything → exception states (handled by _ALWAYS_ALLOWED_TO, listed here for docs)
        ('available',          'recalled',             'recall.manage',  ''),
        ('available',          'quarantined_holdback', 'recall.manage',  ''),
        ('available',          'expired',              '',               'Auto by cron when expiry_datetime passes'),
        ('reserved',           'expired',              '',               ''),
        ('crossmatched',       'expired',              '',               ''),
        ('failed_qc',          'destroyed',            'unit.dispose',   ''),
        ('wasted',             'destroyed',            'unit.dispose',   ''),
        ('expired',            'destroyed',            'unit.dispose',   ''),
        ('recalled',           'destroyed',            'unit.dispose',   ''),
    ]

    for from_s, to_s, perm, guard in allowed:
        UnitStateTransition.objects.get_or_create(
            from_status=from_s,
            to_status=to_s,
            defaults={'requires_permission': perm, 'guard_rule': guard},
        )

    print(f"Seeded {len(allowed)} state transitions.")
