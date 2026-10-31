"""
Mass Casualty Incident (MCI) domain logic.

When an MCI is activated:
- All O-negative available units are pre-allocated (status → reserved)
- An Alert is created for all staff
- The dashboard shows a red MCI banner

When stood down:
- Pre-allocated units are released back to available
- Another Alert is created
"""
from django.utils import timezone
from django.db import transaction


@transaction.atomic
def activate_mci(branch_id, level, incident_name, actor, notes='', reauth_at=None):
    """Activate an MCI event for the branch. Returns the MCIEvent instance."""
    from .models import MCIEvent, Alert
    from inventory.models import BloodUnit
    from inventory.state_machine import transition_unit
    from audit.utils import create_signature, write_audit

    # Block if one already active
    existing = MCIEvent.active_for_branch(branch_id)
    if existing:
        raise ValueError(f"MCI already active: MCI-{existing.pk}. Stand down first.")

    esign = create_signature(
        signer=actor,
        meaning='mci_activation',
        payload_data={'branch_id': branch_id, 'level': level, 'incident_name': incident_name},
        reauth_at=reauth_at,
    )

    # Pre-allocate all available O-neg units
    o_neg_units = list(
        BloodUnit.objects.select_for_update(nowait=True).filter(
            owner_branch_id=branch_id,
            abo_type='O',
            rh_d_type='neg',
            status='available',
        )
    )

    mci = MCIEvent.objects.create(
        branch_id=branch_id,
        level=level,
        incident_name=incident_name,
        status='active',
        activated_by=actor,
        activated_at=timezone.now(),
        preallocated_unit_pks=[u.pk for u in o_neg_units],
        notes=notes,
        esign_activate=esign,
    )

    for unit in o_neg_units:
        transition_unit(unit, 'reserved', actor,
                        reason=f"MCI-{mci.pk} pre-allocation — {incident_name or 'MCI activated'}")

    Alert.objects.create(
        branch_id=branch_id,
        alert_type='mci_active',
        severity='critical',
        message=(
            f"MCI ACTIVATED — {mci.get_level_display()}. "
            f"{'Incident: ' + incident_name + '. ' if incident_name else ''}"
            f"{len(o_neg_units)} O-neg unit(s) pre-allocated. "
            f"Routine XM requirements suspended for emergency releases. "
            f"Activated by {actor}."
        ),
        entity_table='core_mcievent',
        entity_id=mci.pk,
    )

    write_audit(
        actor=actor,
        action='mci.activated',
        entity_table='core_mcievent',
        entity_id=mci.pk,
        after={'level': level, 'o_neg_allocated': len(o_neg_units), 'incident': incident_name},
    )

    return mci


@transaction.atomic
def standdown_mci(mci, actor, notes='', reauth_at=None):
    """Stand down an active MCI event."""
    from .models import Alert
    from inventory.models import BloodUnit
    from inventory.state_machine import transition_unit
    from audit.utils import create_signature, write_audit

    if mci.status != 'active':
        raise ValueError("MCI is not active.")

    esign = create_signature(
        signer=actor,
        meaning='mci_standdown',
        payload_data={'mci_id': mci.pk},
        reauth_at=reauth_at,
    )

    # Release still-reserved pre-allocated units back to available
    released = 0
    for unit_pk in mci.preallocated_unit_pks:
        try:
            unit = BloodUnit.objects.select_for_update(nowait=True).get(
                pk=unit_pk, status='reserved'
            )
            transition_unit(unit, 'available', actor,
                            reason=f"MCI-{mci.pk} stood down — unit released")
            released += 1
        except BloodUnit.DoesNotExist:
            pass

    mci.status = 'stood_down'
    mci.stood_down_by = actor
    mci.stood_down_at = timezone.now()
    mci.esign_standdown = esign
    if notes:
        mci.notes = (mci.notes + '\n' + notes).strip()
    mci.save(update_fields=['status', 'stood_down_by', 'stood_down_at', 'esign_standdown', 'notes'])

    Alert.objects.create(
        branch_id=mci.branch_id,
        alert_type='mci_stood_down',
        severity='warning',
        message=(
            f"MCI STOOD DOWN — MCI-{mci.pk} ({mci.get_level_display()}). "
            f"{released} pre-allocated O-neg unit(s) returned to available stock. "
            f"Stood down by {actor}."
        ),
        entity_table='core_mcievent',
        entity_id=mci.pk,
    )

    write_audit(
        actor=actor,
        action='mci.stood_down',
        entity_table='core_mcievent',
        entity_id=mci.pk,
        after={'released_units': released, 'notes': notes},
    )

    return mci
