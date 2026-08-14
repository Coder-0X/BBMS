from datetime import timedelta

from django.db import models
from django.utils import timezone

from core.choices import (
    ABO_CHOICES,
    COMPONENT_NAME_CHOICES,
    RH_CHOICES,
    UNIT_STATE_CHOICES,
)


class BloodComponent(models.Model):
    """Master list of blood component types.

    shelf_life_days and ml_per_unit drive the automatic expiry-date and
    unit-count calculations on BloodUnit, so they live here instead of
    being hardcoded, and can be tuned per hospital policy from the admin
    or the Components screen without touching code.
    """

    component_name = models.CharField(
        max_length=60,
        unique=True,
        choices=COMPONENT_NAME_CHOICES,
    )
    description = models.CharField(max_length=255, blank=True, null=True)
    shelf_life_days = models.PositiveIntegerField(
        help_text='Days from collection until this component expires.',
    )
    ml_per_unit = models.PositiveIntegerField(
        default=450,
        help_text='mL that counts as "1 unit" of this component '
        '(e.g. 450 for a whole-blood/RBC bag, 200 for plasma).',
    )
    split_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text='% of the original whole-blood donation volume that '
        'becomes this component when a donation passes lab screening and '
        'is auto-separated. Leave blank if this component is not produced '
        'by auto-separation (it can still be added to inventory manually).',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['component_name']

    def __str__(self) -> str:
        return self.component_name


class BloodUnit(models.Model):
    unit_code = models.CharField(max_length=40, unique=True, blank=True)
    donation = models.ForeignKey(
        'donors.Donation',
        on_delete=models.CASCADE,
        related_name='blood_units',
        blank=True,
        null=True,
        help_text='Source donation. When set, the collection date/time '
        'and expiry are taken from the donation automatically.',
    )
    component = models.ForeignKey(BloodComponent, on_delete=models.CASCADE)
    blood_group = models.CharField(max_length=5, choices=ABO_CHOICES)
    rh_factor = models.CharField(max_length=10, choices=RH_CHOICES)
    quantity_ml = models.PositiveIntegerField()
    collected_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text='When the blood was actually drawn. Auto-filled from '
        'the linked donation if left blank. This is what expiry is '
        'calculated from, not the date it was tested or shelved.',
    )
    expiry_date = models.DateField(
        blank=True,
        null=True,
        editable=False,
        help_text='Calculated automatically: collection date + the '
        "component's shelf life. Not editable directly.",
    )
    unit_state = models.CharField(
        max_length=20,
        choices=UNIT_STATE_CHOICES,
        default='Available',
    )

    class Meta:
        ordering = ['expiry_date']
        indexes = [
            models.Index(fields=['unit_state', 'expiry_date']),
            models.Index(fields=['blood_group', 'rh_factor', 'unit_state']),
        ]

    def __str__(self) -> str:
        comp_name = self.component.component_name if self.component else 'Unit'
        return f'{self.unit_code} - {comp_name} ({self.blood_group}{self.rh_factor}, {self.quantity_ml} mL - {self.unit_state})'

    @property
    def units_available(self):
        """How many 'units' this bag represents, given its component's
        mL-per-unit conversion (e.g. 240mL of plasma at 200mL/unit -> 1.2
        units)."""
        if not self.component or not self.component.ml_per_unit:
            return None
        return round(self.quantity_ml / self.component.ml_per_unit, 2)

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    def save(self, *args, **kwargs):
        # Auto-generate unit_code if blank
        if not self.unit_code or not str(self.unit_code).strip():
            if self.donation_id:
                don_code = self.donation.donation_code or f"DON-{self.donation_id}"
                c_name = self.component.component_name if self.component else "UNT"
                abbrev = "".join(w[0] for w in c_name.split()).upper()
                code = f"{don_code}-{abbrev}"
            else:
                count = BloodUnit.objects.count() + 1
                code = f"UNT-{count:05d}"
            orig_code = code
            counter = 1
            while BloodUnit.objects.filter(unit_code=code).exclude(pk=self.pk).exists():
                code = f"{orig_code}-{counter}"
                counter += 1
            self.unit_code = code

        # Donation is the single source of truth for collection time when
        # linked - it always wins over whatever was previously stored.
        if self.donation_id and self.donation.donation_datetime:
            self.collected_at = self.donation.donation_datetime

        if self.collected_at and self.component_id:
            self.expiry_date = (
                self.collected_at + timedelta(days=self.component.shelf_life_days)
            ).date()

        super().save(*args, **kwargs)

        # Auto-sync Inventory record for this BloodUnit
        Inventory = self._meta.apps.get_model('inventory', 'Inventory')
        inv, created = Inventory.objects.get_or_create(
            blood_unit=self,
            defaults={
                'available_quantity': self.quantity_ml if self.unit_state == 'Available' else 0,
                'reserved_quantity': self.quantity_ml if self.unit_state == 'Reserved' else 0,
                'storage_status': self.unit_state if self.unit_state in ('Available', 'Reserved', 'Issued', 'Expired') else 'Quarantined',
            },
        )
        if not created:
            if self.unit_state == 'Available':
                inv.available_quantity = self.quantity_ml
                inv.reserved_quantity = 0
                inv.storage_status = 'Available'
            elif self.unit_state == 'Reserved':
                inv.available_quantity = 0
                inv.reserved_quantity = self.quantity_ml
                inv.storage_status = 'Reserved'
            elif self.unit_state == 'Issued':
                inv.available_quantity = 0
                inv.reserved_quantity = 0
                inv.storage_status = 'Issued'
            elif self.unit_state == 'Expired':
                inv.available_quantity = 0
                inv.reserved_quantity = 0
                inv.storage_status = 'Expired'
            else:
                inv.available_quantity = 0
                inv.reserved_quantity = 0
                inv.storage_status = 'Quarantined'
            inv.save()

        if self.donation_id and not self.donation.units_generated:
            self.donation.units_generated = True
            self.donation.save(update_fields=['units_generated'])


class Inventory(models.Model):
    blood_unit = models.OneToOneField(BloodUnit, on_delete=models.CASCADE)
    available_quantity = models.PositiveIntegerField()
    reserved_quantity = models.PositiveIntegerField(default=0)
    location = models.CharField(max_length=100, blank=True, null=True)
    storage_status = models.CharField(max_length=20, default='Available')

    class Meta:
        indexes = [
            models.Index(fields=['storage_status']),
        ]

    def __str__(self) -> str:
        return f'{self.blood_unit} ({self.available_quantity})'
