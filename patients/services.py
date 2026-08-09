"""Crossmatch workflow logic: booking a unit against a request, recording
the compatibility test outcome, and auto-releasing stale reservations.
"""

from django.db import transaction
from django.utils import timezone

from .models import Crossmatch


def _sync_inventory_for_unit(unit):
    inventory = getattr(unit, 'inventory', None)
    if not inventory:
        return
    if unit.unit_state == 'Reserved':
        inventory.available_quantity = 0
        inventory.reserved_quantity = unit.quantity_ml
        inventory.storage_status = 'Reserved'
    elif unit.unit_state == 'Available':
        inventory.available_quantity = unit.quantity_ml
        inventory.reserved_quantity = 0
        inventory.storage_status = 'Available'
    elif unit.unit_state == 'Issued':
        inventory.available_quantity = 0
        inventory.reserved_quantity = 0
        inventory.storage_status = 'Issued'
    elif unit.unit_state == 'Expired':
        inventory.available_quantity = 0
        inventory.reserved_quantity = 0
        inventory.storage_status = 'Expired'
    inventory.save(
        update_fields=['available_quantity', 'reserved_quantity', 'storage_status']
    )


def matching_units_for_request(blood_request):
    """Exact-match available units for a request: same component, same
    ABO group, same Rh, not expired, and excluding units that previously
    failed crossmatch compatibility for this patient/request. Ordered
    soonest-expiry-first (FEFO) so older stock gets used before it lapses."""
    from inventory.models import BloodUnit

    incompatible_unit_ids = Crossmatch.objects.filter(
        blood_request__patient=blood_request.patient,
        compatibility_result='Incompatible',
    ).values_list('blood_unit_id', flat=True)

    return BloodUnit.objects.filter(
        component=blood_request.required_component,
        blood_group=blood_request.required_blood_group,
        rh_factor=blood_request.required_rh,
        unit_state='Available',
    ).exclude(
        id__in=incompatible_unit_ids
    ).order_by('expiry_date')


def incompatible_crossmatches_for_request(blood_request):
    """Returns past crossmatches that failed compatibility for this patient."""
    return Crossmatch.objects.filter(
        blood_request__patient=blood_request.patient,
        compatibility_result='Incompatible',
    ).select_related('blood_unit', 'blood_unit__component', 'blood_request')


@transaction.atomic
def book_unit(blood_request, blood_unit, crossmatch_code):
    """Lab reserves a specific matching unit against a request."""
    crossmatch = Crossmatch.objects.create(
        crossmatch_code=crossmatch_code,
        blood_request=blood_request,
        blood_unit=blood_unit,
    )
    blood_unit.unit_state = 'Reserved'
    blood_unit.save(update_fields=['unit_state'])
    _sync_inventory_for_unit(blood_unit)

    blood_request.request_status = 'Booked'
    blood_request.save(update_fields=['request_status'])
    return crossmatch


@transaction.atomic
def record_compatibility_result(crossmatch, is_compatible):
    """Lab records the outcome of the physical crossmatch test.

    Compatible   -> unit stays reserved, ready to issue.
    Incompatible -> unit is released back to Available inventory and the
                     request goes back to Pending so another unit can be
                     booked against it.
    """
    crossmatch.crossmatched_at = timezone.now()
    unit = crossmatch.blood_unit

    if is_compatible:
        crossmatch.compatibility_result = 'Compatible'
        crossmatch.crossmatch_status = 'Passed'
    else:
        crossmatch.compatibility_result = 'Incompatible'
        crossmatch.crossmatch_status = 'Failed'
        unit.unit_state = 'Available'
        unit.save(update_fields=['unit_state'])
        _sync_inventory_for_unit(unit)
        crossmatch.blood_request.request_status = 'Pending'
        crossmatch.blood_request.save(update_fields=['request_status'])

    crossmatch.save(
        update_fields=['crossmatched_at', 'compatibility_result', 'crossmatch_status']
    )
    return crossmatch


@transaction.atomic
def issue_unit(crossmatch):
    """Called once a BloodIssue is recorded against a passed crossmatch."""
    unit = crossmatch.blood_unit
    unit.unit_state = 'Issued'
    unit.save(update_fields=['unit_state'])
    _sync_inventory_for_unit(unit)

    crossmatch.crossmatch_status = 'Issued'
    crossmatch.save(update_fields=['crossmatch_status'])

    crossmatch.blood_request.request_status = 'Fulfilled'
    crossmatch.blood_request.save(update_fields=['request_status'])


@transaction.atomic
def release_expired_crossmatches():
    """Release any Booked reservation whose 48h window has passed without
    being issued. Returns the number released."""
    now = timezone.now()
    stale = Crossmatch.objects.filter(
        crossmatch_status='Booked',
        reserved_until__lt=now,
    )
    count = 0
    for crossmatch in stale:
        unit = crossmatch.blood_unit
        if unit.unit_state == 'Reserved':
            unit.unit_state = 'Available'
            unit.save(update_fields=['unit_state'])
        _sync_inventory_for_unit(unit)

        crossmatch.crossmatch_status = 'Released'
        crossmatch.save(update_fields=['crossmatch_status'])

        if crossmatch.blood_request.request_status == 'Booked':
            crossmatch.blood_request.request_status = 'Pending'
            crossmatch.blood_request.save(update_fields=['request_status'])
        count += 1
    return count
