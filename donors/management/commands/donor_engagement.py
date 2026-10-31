"""
management command: python manage.py donor_engagement

Runs proactive donor retention checks and raises alerts:
  1. Lapsed donors (no donation in >6 months) — output list for outreach team
  2. Deferral expiry — donors whose temporary deferral has lapsed (eligible again)
  3. Pending milestones — donors whose milestone certificate hasn't been printed
  4. Donors eligible for a donation today (active, interval met) — daily eligible pool

Run daily from cron:
    0 8 * * *  python /path/manage.py donor_engagement
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Donor engagement check: lapsed, eligible-again, milestones, daily pool.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--lapsed-months', type=int, default=6,
            help='Mark donors as lapsed after this many months (default: 6)',
        )
        parser.add_argument(
            '--quiet', action='store_true', default=False,
            help='Suppress detailed output',
        )
        parser.add_argument(
            '--send-recall-emails', action='store_true', default=False,
            help='Email donors whose temporary deferral just expired to invite them back.',
        )

    def handle(self, *args, **options):
        lapsed_months = options['lapsed_months']
        quiet = options['quiet']
        send_recall = options['send_recall_emails']
        today = timezone.now().date()
        cutoff = today - timedelta(days=lapsed_months * 30)

        from donors.models import Donor, DonorMilestone, Donation
        from core.models import Branch

        stats = {
            'total_donors': 0,
            'lapsed': 0,
            'eligible_again': 0,
            'pending_milestones': 0,
            'daily_pool': 0,
        }

        for branch in Branch.objects.filter(active=True):
            branch_donors = Donor.objects.filter(registration_branch_id=branch.pk)
            stats['total_donors'] += branch_donors.count()

            # 1. Lapsed donors
            lapsed = branch_donors.filter(
                last_donation_date__lt=cutoff,
                deferral_status='active',
            )
            stats['lapsed'] += lapsed.count()
            if not quiet and lapsed.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"[{branch.name}] {lapsed.count()} lapsed donors (>{lapsed_months}mo since last donation)"
                    )
                )

            # 2. Donors eligible again after temporary deferral
            eligible_again = list(branch_donors.filter(
                deferral_status='temporary_defer',
                deferral_until__lte=today,
            ).select_related('subject'))
            for d in eligible_again:
                d.deferral_status = 'active'
                d.deferral_reason = ''
                d.save(update_fields=['deferral_status', 'deferral_reason'])
                if send_recall:
                    _send_recall_email(d, self.stdout)
            stats['eligible_again'] += len(eligible_again)
            if not quiet and eligible_again:
                self.stdout.write(
                    f"[{branch.name}] {len(eligible_again)} donor(s) cleared from temporary deferral"
                )

            # 3. Pending milestone certificates
            pending_ms = DonorMilestone.objects.filter(
                donor__registration_branch_id=branch.pk,
                certificate_generated=False,
            )
            stats['pending_milestones'] += pending_ms.count()
            if not quiet and pending_ms.count():
                self.stdout.write(
                    f"[{branch.name}] {pending_ms.count()} milestone certificate(s) pending generation"
                )

            # 4. Daily eligible pool (active, not donated in last 56 days for males / 112 for females)
            male_cutoff   = today - timedelta(days=56)
            female_cutoff = today - timedelta(days=112)
            daily_pool = branch_donors.filter(
                deferral_status='active',
            ).filter(
                models_q_eligible(male_cutoff, female_cutoff)
            )
            stats['daily_pool'] += daily_pool.count()
            if not quiet:
                self.stdout.write(
                    f"[{branch.name}] {daily_pool.count()} donor(s) eligible to donate today"
                )

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Donor Engagement Summary ==="))
        self.stdout.write(f"Total donors tracked:     {stats['total_donors']}")
        self.stdout.write(f"Lapsed (>{lapsed_months}mo):            {stats['lapsed']}")
        self.stdout.write(f"Re-activated deferrals:   {stats['eligible_again']}")
        self.stdout.write(f"Pending certificates:     {stats['pending_milestones']}")
        self.stdout.write(f"Daily eligible pool:      {stats['daily_pool']}")


def _send_recall_email(donor, stdout=None):
    """Send a 'you're eligible to donate again' email to a donor whose deferral just expired."""
    import re
    from django.core.mail import send_mail
    from django.conf import settings

    EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

    try:
        from privacy.vault import decrypt
        contact_plain = decrypt(donor.subject.contact_enc) if donor.subject.contact_enc else ''
    except Exception:
        return

    m = EMAIL_RE.search(contact_plain)
    if not m:
        return
    email = m.group()

    try:
        name = donor.subject.display_name
    except Exception:
        name = 'Valued Donor'

    branch_name = donor.registration_branch.name
    subject = f"You are eligible to donate blood again — {branch_name}"
    body = (
        f"Dear {name},\n\n"
        f"We are pleased to let you know that your temporary deferral has now expired "
        f"and you are eligible to donate blood again at {branch_name}.\n\n"
        f"Your donation saves lives. Please visit us at your earliest convenience.\n\n"
        f"Thank you for your commitment to blood donation.\n\n"
        f"---\n"
        f"{branch_name} Blood Bank\n"
        f"Do not reply to this automated message.\n"
    )
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@bloodbank.local')
    try:
        send_mail(subject, body, from_email, [email], fail_silently=True)
        if stdout:
            stdout.write(f"  Recall email sent to {email}")
    except Exception:
        pass


def models_q_eligible(male_cutoff, female_cutoff):
    """Q object for donors who are interval-eligible to donate today."""
    from django.db.models import Q
    return (
        Q(sex='M', last_donation_date__lte=male_cutoff) |
        Q(sex='M', last_donation_date__isnull=True) |
        Q(sex='F', last_donation_date__lte=female_cutoff) |
        Q(sex='F', last_donation_date__isnull=True) |
        Q(sex='U', last_donation_date__lte=male_cutoff) |
        Q(sex='U', last_donation_date__isnull=True)
    )
