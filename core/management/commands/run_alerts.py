"""
management command: python manage.py run_alerts

Run this from a cron job every 5 minutes:
    */5 * * * *  python /path/to/manage.py run_alerts

Checks all branches for: low inventory, near-expiry units,
pending emergency release reviews, and expired units.
No daemon needed — plain cron.
"""
from django.core.management.base import BaseCommand
from core.models import Branch
from core.alerts import check_all_alerts
from inventory.models import BloodUnit
from django.utils import timezone


class Command(BaseCommand):
    help = 'Check inventory and raise alerts. Run every 5 minutes via cron.'

    def handle(self, *args, **options):
        # Auto-expire units where expiry_datetime has passed
        expired_count = BloodUnit.objects.filter(
            expiry_datetime__lte=timezone.now(),
            status='available',
        ).update(status='expired')

        if expired_count:
            self.stdout.write(f"Auto-expired {expired_count} unit(s).")

        # Run alert checks per branch
        for branch in Branch.objects.filter(active=True):
            check_all_alerts(branch)
            self.stdout.write(f"Alert check done for {branch}.")

        self.stdout.write(self.style.SUCCESS("Done."))
