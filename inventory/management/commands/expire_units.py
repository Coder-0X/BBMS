from django.core.management.base import BaseCommand

from inventory.services import expire_units


class Command(BaseCommand):
    help = (
        'Mark any blood unit past its expiry_date as Expired and free up '
        'its inventory row. Safe to run repeatedly - intended to be '
        'scheduled hourly/daily via cron. The relevant list screens also '
        'run this check on page load, so this command is a backstop for '
        'when nobody is actively viewing the app.'
    )

    def handle(self, *args, **options):
        count = expire_units()
        if count:
            self.stdout.write(self.style.WARNING(f'Expired {count} blood unit(s).'))
        else:
            self.stdout.write(self.style.SUCCESS('No units needed expiring.'))
