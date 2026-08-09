"""Business logic for turning a passed donation into separated,
ready-to-store blood component units.

Kept out of models.py / views.py so both the lab-test signal and any
management command / admin action can call the same code path.
"""

from django.utils import timezone

from core.choices import COMPONENT_ABBREVIATIONS

from .models import BloodComponent, BloodUnit, Inventory


def _next_unit_code(donation, component):
    abbreviation = COMPONENT_ABBREVIATIONS.get(component.component_name, 'CMP')
    base = f'{donation.donation_code}-{abbreviation}'
    code = base
    suffix = 1
    # Guards against re-running on a donation that already has units
    # (shouldn't happen because of the units_generated flag, but a unique
    # constraint violation here would be a confusing 500, so be defensive).
    while BloodUnit.objects.filter(unit_code=code).exists():
        suffix += 1
        code = f'{base}-{suffix}'
    return code


def generate_units_from_donation(donation, abo_group, rh_factor):
    """Split a whole-blood donation into its component BloodUnits.

    Only components with a configured split_percentage are auto-produced.
    Volumes are derived from the donation's own quantity_ml (the amount
    actually drawn), not a fixed assumption, so partial/short draws are
    handled proportionally. Collection time and therefore expiry are
    inherited from the donation via BloodUnit.save().

    If units already exist for this donation (e.g. from an earlier edit),
    this reactivates them, syncs their ABO/Rh typing, and restores their
    available inventory.
    """
    if donation.blood_units.exists():
        created_units = []
        for unit in donation.blood_units.all():
            unit.blood_group = abo_group
            unit.rh_factor = rh_factor
            unit.unit_state = 'Available'
            unit.save(update_fields=['blood_group', 'rh_factor', 'unit_state'])

            inv, created = Inventory.objects.get_or_create(
                blood_unit=unit,
                defaults={
                    'available_quantity': unit.quantity_ml,
                    'reserved_quantity': 0,
                    'storage_status': 'Available',
                },
            )
            if not created:
                inv.available_quantity = unit.quantity_ml
                inv.storage_status = 'Available'
                inv.save(update_fields=['available_quantity', 'storage_status'])
            created_units.append(unit)

        donation.units_generated = True
        donation.status = 'Passed'
        donation.save(update_fields=['units_generated', 'status'])
        return created_units

    components = BloodComponent.objects.filter(
        is_active=True,
        split_percentage__isnull=False,
    )

    created_units = []
    for component in components:
        quantity_ml = round(
            donation.quantity_ml * float(component.split_percentage) / 100
        )
        if quantity_ml <= 0:
            continue

        unit = BloodUnit(
            unit_code=_next_unit_code(donation, component),
            donation=donation,
            component=component,
            blood_group=abo_group,
            rh_factor=rh_factor,
            quantity_ml=quantity_ml,
            unit_state='Available',
        )
        unit.save()  # expiry_date + collected_at computed inside save()

        Inventory.objects.get_or_create(
            blood_unit=unit,
            defaults={
                'available_quantity': unit.quantity_ml,
                'reserved_quantity': 0,
                'storage_status': 'Available',
            },
        )
        created_units.append(unit)

    donation.units_generated = True
    donation.status = 'Passed'
    donation.save(update_fields=['units_generated', 'status'])
    return created_units


def expire_units():
    """Flip any unit past its expiry date to 'Expired' and free up its
    inventory row. Safe to call repeatedly (e.g. from a view or a cron
    job) - only touches units that are actually stale.

    Returns the number of units expired.
    """
    today = timezone.localdate()
    stale_units = BloodUnit.objects.filter(
        expiry_date__lt=today,
        unit_state__in=['Available', 'Reserved'],
    )
    count = 0
    for unit in stale_units:
        unit.unit_state = 'Expired'
        unit.save(update_fields=['unit_state'])
        inventory = getattr(unit, 'inventory', None)
        if inventory:
            inventory.available_quantity = 0
            inventory.reserved_quantity = 0
            inventory.storage_status = 'Expired'
            inventory.save(
                update_fields=[
                    'available_quantity',
                    'reserved_quantity',
                    'storage_status',
                ]
            )
        count += 1
    return count
