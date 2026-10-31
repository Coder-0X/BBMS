"""
Cross-site blood unit request.
One branch requests units from another; the sending branch fulfils by initiating a Transfer.
"""
from django.db import transaction
from django.utils import timezone

from .models import BloodUnit, Transfer
from .state_machine import transition_unit
from audit.utils import write_audit


class CrossSiteRequestError(Exception):
    pass


@transaction.atomic
def create_cross_site_request(
    requesting_branch,
    fulfilling_branch,
    component_class: str,
    abo_type: str,
    rh_d_type: str,
    units_needed: int,
    reason: str,
    actor,
) -> list[Transfer]:
    """
    Find available compatible units at the fulfilling branch and create
    Transfer rows (status='requested') for each.
    Returns the list of Transfer objects created.
    """
    if units_needed < 1:
        raise CrossSiteRequestError("Must request at least 1 unit.")
    if requesting_branch.pk == fulfilling_branch.pk:
        raise CrossSiteRequestError("Cannot request units from the same branch.")

    # Find available units at the fulfilling branch
    qs = BloodUnit.objects.select_for_update(nowait=True).filter(
        owner_branch=fulfilling_branch,
        status='available',
        component_class=component_class,
        abo_type=abo_type,
        rh_d_type=rh_d_type,
    ).order_by('expiry_datetime')  # FEFO

    available = list(qs[:units_needed])
    if len(available) < units_needed:
        raise CrossSiteRequestError(
            f"Only {len(available)} unit(s) available at {fulfilling_branch.name}; {units_needed} requested."
        )

    transfers = []
    for unit in available:
        transition_unit(unit, 'transferred_out', actor,
                        reason=f"Cross-site request to {requesting_branch.name}: {reason}")
        t = Transfer.objects.create(
            blood_unit=unit,
            from_branch=fulfilling_branch,
            to_branch=requesting_branch,
            initiated_by=actor,
            status='approved',
            reason=reason,
        )
        write_audit(
            actor=actor,
            action='transfer.cross_site_created',
            entity_table='inventory_transfer',
            entity_id=t.pk,
            after={
                'unit_did': unit.did,
                'from_branch': fulfilling_branch.name,
                'to_branch': requesting_branch.name,
            },
        )
        transfers.append(t)

    return transfers
