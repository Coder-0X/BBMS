from django.db.models.signals import post_save
from django.dispatch import receiver

from inventory.services import generate_units_from_donation

from .models import BloodTest


@receiver(post_save, sender=BloodTest)
def handle_blood_test_result(sender, instance, **kwargs):
    """React to the auto-computed overall_result on a BloodTest.

    1. Lab record is the authoritative medical source of truth:
       Update the donor's on-file blood group and Rh factor to match the lab typing.

    2. Synchronize inventory units (if any exist for this donation) so they
       reflect the authoritative ABO/Rh typing.

    3. Handle donation status and unit splitting:
       Fail  -> donation is rejected, nothing enters inventory.
       Pass  -> donation is split into component BloodUnits (once only,
                guarded by Donation.units_generated) using the lab-confirmed
                ABO/Rh typing.
    """
    donation = instance.donation
    if not donation:
        return

    # 1. Update donor's profile with confirmed lab typing
    donor = donation.donor
    if donor and instance.abo_group and instance.rh_factor and (
        donor.blood_group != instance.abo_group or donor.rh_factor != instance.rh_factor
    ):
        donor.blood_group = instance.abo_group
        donor.rh_factor = instance.rh_factor
        donor.save(update_fields=['blood_group', 'rh_factor'])

    # 2. Handle donation status & inventory units
    if instance.overall_result == 'Fail':
        if donation.status != 'Rejected':
            donation.status = 'Rejected'
            donation.save(update_fields=['status'])
        # Quarantine any existing units so they do not show as available inventory
        if donation.blood_units.exists():
            for unit in donation.blood_units.all():
                unit.unit_state = 'Discarded'
                unit.save(update_fields=['unit_state'])
                inv = getattr(unit, 'inventory', None)
                if inv:
                    inv.available_quantity = 0
                    inv.storage_status = 'Quarantined'
                    inv.save(update_fields=['available_quantity', 'storage_status'])
    elif instance.overall_result == 'Pass':
        generate_units_from_donation(
            donation,
            abo_group=instance.abo_group,
            rh_factor=instance.rh_factor,
        )
    elif donation.status not in ('Rejected', 'Passed'):
        donation.status = 'Testing'
        donation.save(update_fields=['status'])
