"""
management command: python manage.py send_campaign_emails

Dispatches email outreach for active retention campaigns whose channel is
'email' or 'mixed'. For each enrolled donor who has not yet been contacted:
  1. Decrypts donor.subject.contact_enc
  2. Extracts an email address (regex — freeform contact field)
  3. Renders the campaign message_template with {name} and {last_donation}
  4. Sends the email via Django's configured EMAIL_BACKEND
  5. Marks the CampaignEnrollment as 'contacted' with contacted_at = now

Run daily from cron (or whenever campaigns are active):
    0 9 * * *  python /path/manage.py send_campaign_emails

Options:
  --dry-run     Print what would be sent without actually sending.
  --campaign    Only process this campaign PK (default: all active ones).
  --limit       Max emails per campaign (default: unlimited).
"""
import re
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings


EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')


def _extract_email(contact_plain: str) -> str | None:
    """Return the first email address found in freeform contact text, or None."""
    if not contact_plain:
        return None
    m = EMAIL_RE.search(contact_plain)
    return m.group() if m else None


def _decrypt_contact(subject) -> str:
    """Decrypt subject.contact_enc; return empty string on failure."""
    if not subject.contact_enc:
        return ''
    try:
        from privacy.vault import decrypt
        return decrypt(subject.contact_enc)
    except Exception:
        return ''


def _render_template(template: str, name: str, last_donation) -> str:
    last = last_donation.strftime('%d %b %Y') if last_donation else 'a while ago'
    return template.replace('{name}', name).replace('{last_donation}', last)


class Command(BaseCommand):
    help = 'Dispatch email outreach for active retention campaigns.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', default=False,
                            help='Print emails that would be sent without sending.')
        parser.add_argument('--campaign', type=int, default=None,
                            help='Only process this campaign PK.')
        parser.add_argument('--limit', type=int, default=None,
                            help='Max emails to send per campaign.')

    def handle(self, *args, **options):
        from donors.models import RetentionCampaign, CampaignEnrollment

        dry_run = options['dry_run']
        campaign_pk = options['campaign']
        limit = options['limit']
        now = timezone.now()
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@bloodbank.local')

        qs = RetentionCampaign.objects.filter(status='active', channel__in=['email', 'mixed'])
        if campaign_pk:
            qs = qs.filter(pk=campaign_pk)

        total_sent = 0
        total_skipped = 0

        for campaign in qs:
            sent_this = 0
            skipped_this = 0

            enrollments = (
                CampaignEnrollment.objects
                .filter(campaign=campaign, status='enrolled')
                .select_related('donor__subject')
            )

            self.stdout.write(
                f"\nCampaign: {campaign.name} "
                f"({enrollments.count()} enrolled, not yet contacted)"
            )

            for enroll in enrollments:
                if limit and sent_this >= limit:
                    break

                donor = enroll.donor
                contact_plain = _decrypt_contact(donor.subject)
                email = _extract_email(contact_plain)

                if not email:
                    skipped_this += 1
                    continue

                name = donor.subject.display_name
                body = _render_template(
                    campaign.message_template,
                    name=name,
                    last_donation=donor.last_donation_date,
                )
                subject_line = f"{campaign.name} — {campaign.branch.name}"

                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [DRY RUN] Would email {email}: {subject_line[:60]}"
                        )
                    )
                else:
                    try:
                        send_mail(
                            subject=subject_line,
                            message=body,
                            from_email=from_email,
                            recipient_list=[email],
                            fail_silently=False,
                        )
                        enroll.status = 'contacted'
                        enroll.contacted_at = now
                        enroll.save(update_fields=['status', 'contacted_at'])
                        sent_this += 1
                        self.stdout.write(f"  Sent to {email}")
                    except Exception as exc:
                        skipped_this += 1
                        self.stdout.write(
                            self.style.ERROR(f"  Failed {email}: {exc}")
                        )

            total_sent += sent_this
            total_skipped += skipped_this
            self.stdout.write(
                f"  => Sent: {sent_this}  Skipped (no email): {skipped_this}"
            )

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{prefix}Done. Total sent: {total_sent}  Skipped: {total_skipped}"
            )
        )
