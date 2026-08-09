from django.core.management.base import BaseCommand

from patients.services import release_expired_crossmatches


class Command(BaseCommand):
    help = (
        'Release any crossmatch reservation whose 48-hour hold has '
        'passed without the unit being issued, putting the unit back '
        'into Available inventory and the request back to Pending. '
        'Safe to run repeatedly - intended to be scheduled via cron. '
        'The Crossmatch list screen also runs this check on page load.'
    )

    def handle(self, *args, **options):
        count = release_expired_crossmatches()
        if count:
            self.stdout.write(
                self.style.WARNING(f'Released {count} expired reservation(s).')
            )
        else:
            self.stdout.write(self.style.SUCCESS('No reservations needed releasing.'))
