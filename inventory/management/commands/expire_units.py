"""
Management command: expire_units

Transitions all blood units past their expiry_datetime to 'expired' status.
Run every 30 minutes via cron/celery beat:
    python manage.py expire_units

AABB §5.19 / FDA 21 CFR 606.122(h): expired units must not be available for issue.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction


class Command(BaseCommand):
    help = 'Expire blood units whose expiry_datetime has passed'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print units that would be expired without changing anything',
        )

    def handle(self, *args, **options):
        from inventory.models import BloodUnit
        from inventory.state_machine import transition_unit

        User = get_user_model()
        # Use first superuser as system actor for audit trail
        actor = User.objects.filter(is_superuser=True).first()
        if actor is None:
            self.stderr.write('No superuser found — cannot write audit trail. Aborting.')
            return

        now = timezone.now()

        # Only expire units in states where expiry is meaningful
        # (already-issued, wasted, destroyed etc. don't need changing)
        expirable_statuses = ['available', 'reserved', 'crossmatched', 'in_testing', 'quarantined']

        units = BloodUnit.objects.filter(
            expiry_datetime__lte=now,
            status__in=expirable_statuses,
        ).select_related('owner_branch')

        count = units.count()
        if count == 0:
            self.stdout.write('No units to expire.')
            return

        if options['dry_run']:
            self.stdout.write(f'DRY RUN — {count} unit(s) would be expired:')
            for u in units[:50]:
                self.stdout.write(f'  {u.did}  expired {u.expiry_datetime}  status={u.status}')
            return

        expired = 0
        failed = 0
        for unit in units:
            try:
                with transaction.atomic():
                    # Re-fetch with lock
                    unit_locked = BloodUnit.objects.select_for_update(nowait=True).get(pk=unit.pk)
                    if unit_locked.expiry_datetime > now:
                        continue  # became valid again somehow (race) — skip
                    if unit_locked.status not in expirable_statuses:
                        continue  # status changed between our query and the lock
                    transition_unit(
                        unit_locked, 'expired', actor,
                        reason=f'Auto-expired by expire_units command at {now:%Y-%m-%d %H:%M} UTC',
                    )
                    expired += 1
            except Exception as e:
                failed += 1
                self.stderr.write(f'  Could not expire {unit.did}: {e}')

        self.stdout.write(
            self.style.SUCCESS(f'Expired {expired} unit(s). Failed: {failed}.')
        )
