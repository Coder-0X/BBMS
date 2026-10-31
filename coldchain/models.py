"""
Cold chain infrastructure — storage equipment, temperature monitoring, excursion management.
"""
from django.db import models
from django.conf import settings
import uuid


COMPONENT_CLASSES = [
    ('RBC', 'Red Blood Cells'),
    ('FFP', 'Fresh Frozen Plasma'),
    ('PLT', 'Platelets'),
    ('CRYO', 'Cryoprecipitate'),
    ('WB', 'Whole Blood'),
    ('GRAN', 'Granulocytes'),
    ('MIXED', 'Mixed'),
]

EQUIPMENT_TYPES = [
    ('fridge', 'Blood Refrigerator (1–6 °C)'),
    ('platelet_agitator', 'Platelet Agitator (20–24 °C)'),
    ('freezer', 'Freezer (−18 °C or below)'),
    ('ult_freezer', 'Ultra-Low Freezer (−65 °C or below)'),
    ('transport_cooler', 'Transport Cooler'),
    ('validated_shipper', 'Validated Shipper'),
]


class ComponentStorageSpec(models.Model):
    """Temperature and agitation requirements for each blood component class."""
    component_class         = models.CharField(max_length=5, choices=COMPONENT_CLASSES, primary_key=True)
    storage_temp_min_c      = models.DecimalField(max_digits=5, decimal_places=1)
    storage_temp_max_c      = models.DecimalField(max_digits=5, decimal_places=1)
    transport_temp_min_c    = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    transport_temp_max_c    = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    requires_agitation      = models.BooleanField(default=False)
    agitation_max_interruption_min = models.SmallIntegerField(null=True, blank=True)
    shelf_life_hours        = models.SmallIntegerField()
    max_temp_excursion_min  = models.SmallIntegerField(default=30)
    source_standard         = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"{self.component_class}: {self.storage_temp_min_c}–{self.storage_temp_max_c} °C"


class StorageEquipment(models.Model):
    """A fridge, freezer, or platelet agitator in a branch."""
    STATUS = [('active', 'Active'), ('maintenance', 'Maintenance'), ('decommissioned', 'Decommissioned')]

    name                    = models.CharField(max_length=200)
    equipment_type          = models.CharField(max_length=20, choices=EQUIPMENT_TYPES)
    sensor_id               = models.CharField(max_length=100, unique=True, blank=True)
    branch                  = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='equipment')
    component_class_allowed = models.CharField(max_length=5, choices=COMPONENT_CLASSES, blank=True)
    calibration_due         = models.DateField(null=True, blank=True)
    status                  = models.CharField(max_length=15, choices=STATUS, default='active')
    location                = models.CharField(max_length=200, blank=True)
    created_at              = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.branch})"

    @property
    def is_overdue_calibration(self):
        from django.utils import timezone
        return self.calibration_due and self.calibration_due < timezone.now().date()


class SensorHealth(models.Model):
    """Heartbeat tracker for each temperature sensor."""
    STATUS = [('ok', 'OK'), ('late', 'Late'), ('offline', 'Offline')]

    sensor_id               = models.CharField(max_length=100, primary_key=True)
    equipment               = models.OneToOneField(StorageEquipment, on_delete=models.CASCADE, related_name='sensor_health')
    last_seen_at            = models.DateTimeField(null=True, blank=True)
    expected_interval_sec   = models.SmallIntegerField(default=300)
    status                  = models.CharField(max_length=10, choices=STATUS, default='ok')

    def __str__(self):
        return f"Sensor {self.sensor_id}: {self.status}"


class TemperatureLog(models.Model):
    """Continuous per-reading log from temperature sensors."""
    SOURCES = [('sensor', 'Sensor'), ('manual', 'Manual Entry')]

    equipment       = models.ForeignKey(StorageEquipment, on_delete=models.PROTECT, related_name='temperature_logs')
    recorded_at     = models.DateTimeField(db_index=True)
    temp_c          = models.DecimalField(max_digits=5, decimal_places=2)
    humidity_pct    = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    agitation_ok    = models.BooleanField(null=True, blank=True)
    source          = models.CharField(max_length=10, choices=SOURCES)
    reading_uuid    = models.UUIDField(default=uuid.uuid4, unique=True)

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"{self.equipment.name} @ {self.recorded_at:%Y-%m-%d %H:%M}: {self.temp_c} °C"


class TemperatureExcursion(models.Model):
    """An out-of-range temperature event affecting stored units."""
    DISPOSITIONS = [
        ('return_to_stock', 'Return to Stock'),
        ('quarantine', 'Quarantine'),
        ('discard', 'Discard'),
    ]

    equipment       = models.ForeignKey(StorageEquipment, on_delete=models.PROTECT, related_name='excursions')
    started_at      = models.DateTimeField()
    ended_at        = models.DateTimeField(null=True, blank=True)
    max_temp_c      = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    min_temp_c      = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    auto_quarantine = models.BooleanField(default=True)
    disposition     = models.CharField(max_length=20, choices=DISPOSITIONS, blank=True)
    disposition_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    disposition_at  = models.DateTimeField(null=True, blank=True)
    justification   = models.TextField(blank=True)
    esign           = models.ForeignKey('audit.ElectronicSignature', null=True, blank=True, on_delete=models.PROTECT)
    created_at      = models.DateTimeField(auto_now_add=True)

    @property
    def is_ongoing(self):
        return self.ended_at is None

    @property
    def duration_minutes(self):
        if self.ended_at and self.started_at:
            return int((self.ended_at - self.started_at).total_seconds() / 60)
        return None

    def __str__(self):
        return f"Excursion on {self.equipment.name} from {self.started_at:%Y-%m-%d %H:%M}"


class ExcursionUnitLink(models.Model):
    """Links a temperature excursion to each blood unit that was in the equipment."""
    excursion       = models.ForeignKey(TemperatureExcursion, on_delete=models.PROTECT, related_name='unit_links')
    blood_unit      = models.ForeignKey('inventory.BloodUnit', on_delete=models.PROTECT, related_name='excursion_links')
    auto_quarantined = models.BooleanField(default=True)

    class Meta:
        unique_together = [('excursion', 'blood_unit')]

    def __str__(self):
        return f"{self.blood_unit.did} in excursion #{self.excursion_id}"


class EquipmentAlarm(models.Model):
    """Active or resolved alarm from storage equipment."""
    ALARM_TYPES = [
        ('high_temp', 'High Temperature'),
        ('low_temp', 'Low Temperature'),
        ('agitation_failure', 'Agitation Failure'),
        ('power_loss', 'Power Loss'),
        ('door_open', 'Door Open Too Long'),
        ('sensor_disconnect', 'Sensor Disconnected'),
        ('calibration_overdue', 'Calibration Overdue'),
        ('battery_low', 'Battery Low'),
    ]

    equipment       = models.ForeignKey(StorageEquipment, on_delete=models.PROTECT, related_name='alarms')
    alarm_type      = models.CharField(max_length=25, choices=ALARM_TYPES)
    triggered_at    = models.DateTimeField()
    cleared_at      = models.DateTimeField(null=True, blank=True)
    ack_by          = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    ack_at          = models.DateTimeField(null=True, blank=True)
    escalation_level = models.SmallIntegerField(default=1)  # 1=staff, 2=supervisor, 3=on-call
    excursion       = models.ForeignKey(TemperatureExcursion, null=True, blank=True, on_delete=models.SET_NULL, related_name='alarms')

    @property
    def is_active(self):
        return self.cleared_at is None

    def __str__(self):
        status = "ACTIVE" if self.is_active else "cleared"
        return f"{self.get_alarm_type_display()} on {self.equipment.name} ({status})"


class UnitReturnCheck(models.Model):
    """Record of whether a returned-from-ward unit can go back to stock."""
    RULES = [('30_minute_rule', '30-Minute Rule'), ('validated_temp', 'Validated Temperature')]
    DECISIONS = [('return_to_stock', 'Return to Stock'), ('discard', 'Discard')]

    blood_unit          = models.ForeignKey('inventory.BloodUnit', on_delete=models.PROTECT, related_name='return_checks')
    issue               = models.ForeignKey('transfusion.IssueTransaction', on_delete=models.PROTECT, related_name='+')
    issued_at           = models.DateTimeField()
    returned_at         = models.DateTimeField()
    minutes_out         = models.SmallIntegerField()
    measured_return_temp_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    rule_applied        = models.CharField(max_length=20, choices=RULES)
    decision            = models.CharField(max_length=20, choices=DECISIONS)
    decided_by          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    esign               = models.ForeignKey('audit.ElectronicSignature', on_delete=models.PROTECT, related_name='+')
    created_at          = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Return check {self.blood_unit.did}: {self.decision} ({self.minutes_out} min out)"


class ShipmentColdChain(models.Model):
    """Temperature data logged during inter-branch unit transport."""
    transfer        = models.OneToOneField('inventory.Transfer', on_delete=models.PROTECT, related_name='cold_chain')
    logger_id       = models.CharField(max_length=100, blank=True)
    origin_branch   = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    destination_branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT, related_name='+')
    departed_at     = models.DateTimeField()
    arrived_at      = models.DateTimeField(null=True, blank=True)
    logger_data_json = models.JSONField(null=True, blank=True)
    excursion_detected = models.BooleanField(default=False)

    def __str__(self):
        return f"Cold chain for transfer {self.transfer_id}: {self.origin_branch} → {self.destination_branch}"
