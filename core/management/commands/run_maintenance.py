from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Runs all scheduled blood-bank housekeeping in one go: expires '
        'stale blood units and releases crossmatch reservations past '
        'their 48-hour window. Point a single cron entry at this, e.g.:\n'
        '  0 * * * * cd /path/to/project && python manage.py run_maintenance'
    )

    def handle(self, *args, **options):
        call_command('expire_units')
        call_command('release_expired_crossmatches')
