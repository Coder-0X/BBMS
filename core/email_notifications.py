"""
Email notifications for blood bank alerts.
Called by _raise_alert() after a new Alert row is created.
Users opt in via notify_critical_alerts / notify_warning_alerts on their profile.
"""
from django.core.mail import send_mail
from django.conf import settings


def send_alert_email(alert):
    """
    Send an email to all opted-in users at the alert's branch.
    Silently swips errors so a mail failure never breaks the alert pipeline.
    """
    from accounts.models import User

    if alert.severity == 'critical':
        recipients = list(
            User.objects.filter(
                branch=alert.branch,
                is_active=True,
                notify_critical_alerts=True,
            ).exclude(email='').values_list('email', flat=True)
        )
    elif alert.severity == 'warning':
        recipients = list(
            User.objects.filter(
                branch=alert.branch,
                is_active=True,
                notify_warning_alerts=True,
            ).exclude(email='').values_list('email', flat=True)
        )
    else:
        return  # info alerts don't send email

    if not recipients:
        return

    subject = f"[{alert.severity.upper()}] Blood Bank Alert — {alert.branch.name}"
    body = (
        f"Alert type: {alert.get_alert_type_display()}\n"
        f"Branch: {alert.branch.name}\n"
        f"Severity: {alert.severity.upper()}\n\n"
        f"{alert.message}\n\n"
        f"---\n"
        f"Log in to review and acknowledge this alert.\n"
        f"Do not reply to this automated message.\n"
    )
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@bloodbank.local')

    try:
        send_mail(subject, body, from_email, recipients, fail_silently=True)
    except Exception:
        pass
