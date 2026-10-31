"""
BloodUnit creation — from donation to component(s).

After a whole blood donation, this module creates the derived blood units
(RBC pack, FFP, platelets, etc.) and assigns each a DID.
Called from the donation workflow after the collection is complete.
"""
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.did import generate_did
from core.models import RefFacility
from audit.utils import write_audit


@transaction.atomic
def create_units_from_whole_blood(donation, component_codes, actor, branch):
    """
    Create blood units from a whole blood donation.
    component_codes: list of ComponentType.code values, e.g. ['RBC-SAG', 'FFP-FZ', 'PLT-PC']
    Returns list of created BloodUnit objects.
    """
    from inventory.models import BloodUnit, ComponentType, ProcessingEvent, UnitLineage

    try:
        facility = RefFacility.objects.get(branch=branch)
    except RefFacility.DoesNotExist:
        raise ValidationError(
            f"Branch '{branch.name}' has no facility reference code configured. "
            "Contact your administrator."
        )
    proc_event = ProcessingEvent.objects.create(
        event_type='whole_blood_separation',
        performed_by=actor,
        performed_at=timezone.now(),
        branch=branch,
        sop_version='1.0',
    )

    created_units = []
    for code in component_codes:
        try:
            component = ComponentType.objects.get(code=code)
        except ComponentType.DoesNotExist:
            raise ValidationError(
                f"Component type code '{code}' is not defined. "
                "Add it in the inventory component catalogue."
            )
        serial = facility.next_serial()
        did = generate_did(facility.facility_code, serial)

        expiry = timezone.now() + timedelta(hours=component.shelf_life_hours)

        unit = BloodUnit.objects.create(
            did=did,
            did_check_char=did[-1],
            donation=donation,
            parent_donation=donation,
            component_type=component,
            component_class=component.component_class,
            abo_type=donation.donor.blood_group_abo,
            rh_d_type=donation.donor.blood_group_rh,
            collection_datetime=donation.donated_at,
            expiry_datetime=expiry,
            owner_branch=branch,
            status='quarantined',
            production_event=proc_event,
            collected_by=donation.collected_by,
            collected_at=donation.donated_at,
        )

        UnitLineage.objects.create(
            processing_event=proc_event,
            parent_donation=donation,
            child_unit=unit,
            relationship='derived_from',
        )

        write_audit(
            actor=actor,
            action='unit.create',
            entity_table='inventory_bloodunit',
            entity_id=unit.pk,
            after={
                'did': did,
                'component': code,
                'donation_id': donation.pk,
                'abo': unit.abo_type,
                'rh_d': unit.rh_d_type,
            },
            branch=branch,
        )
        created_units.append(unit)

    return created_units


@transaction.atomic
def create_apheresis_units(donation, component_codes, actor, branch):
    """
    Create blood units from an apheresis donation (one unit per component type collected).
    Same logic as whole blood separation but event_type differs.
    """
    from inventory.models import BloodUnit, ComponentType, ProcessingEvent, UnitLineage

    try:
        facility = RefFacility.objects.get(branch=branch)
    except RefFacility.DoesNotExist:
        raise ValidationError(
            f"Branch '{branch.name}' has no facility reference code configured. "
            "Contact your administrator."
        )
    proc_event = ProcessingEvent.objects.create(
        event_type='apheresis_collection',
        performed_by=actor,
        performed_at=timezone.now(),
        branch=branch,
        sop_version='1.0',
    )

    created_units = []
    for code in component_codes:
        try:
            component = ComponentType.objects.get(code=code)
        except ComponentType.DoesNotExist:
            raise ValidationError(
                f"Component type code '{code}' is not defined. "
                "Add it in the inventory component catalogue."
            )
        serial = facility.next_serial()
        did = generate_did(facility.facility_code, serial)
        expiry = timezone.now() + timedelta(hours=component.shelf_life_hours)

        unit = BloodUnit.objects.create(
            did=did,
            did_check_char=did[-1],
            donation=donation,
            parent_donation=donation,
            component_type=component,
            component_class=component.component_class,
            abo_type=donation.donor.blood_group_abo,
            rh_d_type=donation.donor.blood_group_rh,
            collection_datetime=donation.donated_at,
            expiry_datetime=expiry,
            owner_branch=branch,
            status='quarantined',
            production_event=proc_event,
            collected_by=donation.collected_by,
            collected_at=donation.donated_at,
        )

        UnitLineage.objects.create(
            processing_event=proc_event,
            parent_donation=donation,
            child_unit=unit,
            relationship='derived_from',
        )

        write_audit(
            actor=actor,
            action='unit.create',
            entity_table='inventory_bloodunit',
            entity_id=unit.pk,
            after={
                'did': did,
                'component': code,
                'donation_id': donation.pk,
                'abo': unit.abo_type,
                'rh_d': unit.rh_d_type,
                'source': 'apheresis',
            },
            branch=branch,
        )
        created_units.append(unit)

    return created_units
