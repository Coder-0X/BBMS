"""
management command: python manage.py remind_post_outcomes

Run from cron every 6 hours (or daily):
    0 */6 * * *  python /path/to/manage.py remind_post_outcomes

Raises pbm_post_hb_gap alerts for RBC issue transactions that:
  - Were issued 24–72 hours ago
  - Still have no PostTransfusionOutcome recorded
  - The request is not emergency/MTP (those get fast-tracked separately)

Reference: AABB PBM Toolkit; NHS GIRFT Blood Programme 2021 —
post-transfusion Hb check at 24–48 h is mandatory for PBM compliance.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from core.models import Alert, Branch
from transfusion.models import IssueTransaction


class Command(BaseCommand):
    help = 'Raise alerts for RBC transfusions missing post-transfusion Hb documentation (24–72 h window).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be alerted without creating Alert objects.',
        )
        parser.add_argument(
            '--min-hours',
            type=int,
            default=24,
            help='Minimum hours since issue before alerting (default 24).',
        )
        parser.add_argument(
            '--max-hours',
            type=int,
            default=72,
            help='Maximum hours since issue to still alert (default 72).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        min_hours = options['min_hours']
        max_hours = options['max_hours']

        now = timezone.now()
        window_start = now - timedelta(hours=max_hours)
        window_end = now - timedelta(hours=min_hours)

        # RBC issues within window with no post outcome recorded
        overdue_issues = (
            IssueTransaction.objects
            .filter(
                issued_at__gte=window_start,
                issued_at__lte=window_end,
                blood_unit__component_type__component_class='RBC',
                request__post_outcome__isnull=True,
            )
            .exclude(request__urgency='emergency_mtp')
            .select_related('blood_unit__component_type', 'request', 'patient')
            .order_by('issued_at')
        )

        total = overdue_issues.count()
        self.stdout.write(
            f"Found {total} RBC issue(s) in {min_hours}–{max_hours}h window with no post-Hb outcome."
        )

        alerted = 0
        for issue in overdue_issues:
            hours_since = (now - issue.issued_at).total_seconds() / 3600
            branch = issue.request.branch

            msg = (
                f"Post-transfusion Hb outcome not recorded for RBC unit {issue.blood_unit.did} "
                f"(Patient #{issue.patient_id}, Request #{issue.request_id}). "
                f"Issued {hours_since:.0f}h ago — document post-Hb within the PBM programme."
            )

            if dry_run:
                self.stdout.write(f"  [DRY-RUN] Would alert branch {branch}: {msg}")
            else:
                _, created = Alert.objects.get_or_create(
                    alert_type='pbm_post_hb_gap',
                    branch=branch,
                    entity_table='transfusion_issuetransaction',
                    entity_id=issue.pk,
                    acknowledged_by=None,
                    defaults={
                        'severity': 'warning',
                        'message': msg,
                    },
                )
                if created:
                    alerted += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Created {alerted} new alert(s)."))
