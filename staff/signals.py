import logging
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.middleware import get_current_ip, get_current_user
from donors.models import Donation, Donor
from inventory.models import BloodComponent, BloodUnit, Inventory
from lab.models import BloodTest
from patients.models import BloodIssue, BloodRequest, Crossmatch, Patient
from staff.models import AuditLog, StaffProfile

logger = logging.getLogger(__name__)


def get_record_identifier(instance):
    for attr in (
        'donor_code',
        'donation_code',
        'unit_code',
        'request_code',
        'crossmatch_code',
        'issue_code',
        'employee_code',
        'component_name',
        'username',
        'patient_code',
        'full_name',
    ):
        val = getattr(instance, attr, None)
        if val:
            return str(val)
    return str(instance.pk) if instance.pk else str(instance)


def get_instance_summary(instance):
    return str(instance)


@receiver(post_save)
def audit_post_save(sender, instance, created, raw, **kwargs):
    if raw:
        return
    # Ignore AuditLog itself
    if sender in (AuditLog,):
        return

    tracked_models = {
        Donor: 'Donors',
        Donation: 'Donations',
        BloodTest: 'Lab Tests',
        BloodUnit: 'Blood Units',
        BloodComponent: 'Components',
        Inventory: 'Inventory',
        Patient: 'Patients',
        BloodRequest: 'Blood Requests',
        Crossmatch: 'Crossmatches',
        BloodIssue: 'Blood Issues',
        StaffProfile: 'Staff Profiles',
        User: 'Users',
    }

    module_name = tracked_models.get(sender)
    if not module_name:
        return

    try:
        user = get_current_user()
        ip_address = get_current_ip()
        action_type = 'CREATE' if created else 'UPDATE'
        record_id = get_record_identifier(instance)
        summary = get_instance_summary(instance)

        description = f'{action_type} on {module_name}: {summary}'

        AuditLog.objects.create(
            user=user,
            action_type=action_type,
            module_name=module_name,
            record_id=record_id,
            description=description,
            ip_address=ip_address,
        )
    except Exception as e:
        logger.warning(f'Failed to record audit log on save: {e}')


@receiver(post_delete)
def audit_post_delete(sender, instance, **kwargs):
    if sender in (AuditLog,):
        return

    tracked_models = {
        Donor: 'Donors',
        Donation: 'Donations',
        BloodTest: 'Lab Tests',
        BloodUnit: 'Blood Units',
        BloodComponent: 'Components',
        Inventory: 'Inventory',
        Patient: 'Patients',
        BloodRequest: 'Blood Requests',
        Crossmatch: 'Crossmatches',
        BloodIssue: 'Blood Issues',
        StaffProfile: 'Staff Profiles',
        User: 'Users',
    }

    module_name = tracked_models.get(sender)
    if not module_name:
        return

    try:
        user = get_current_user()
        ip_address = get_current_ip()
        record_id = get_record_identifier(instance)
        summary = get_instance_summary(instance)

        description = f'DELETE on {module_name}: {summary}'

        AuditLog.objects.create(
            user=user,
            action_type='DELETE',
            module_name=module_name,
            record_id=record_id,
            description=description,
            ip_address=ip_address,
        )
    except Exception as e:
        logger.warning(f'Failed to record audit log on delete: {e}')


@receiver(user_logged_in)
def audit_user_logged_in(sender, request, user, **kwargs):
    try:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')

        AuditLog.objects.create(
            user=user,
            action_type='LOGIN',
            module_name='Security',
            record_id=user.username,
            description=f"User '{user.username}' successfully logged in.",
            ip_address=ip,
        )
    except Exception as e:
        logger.warning(f'Failed to record login audit: {e}')


@receiver(user_logged_out)
def audit_user_logged_out(sender, request, user, **kwargs):
    try:
        if not user or not user.is_authenticated:
            return
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')

        AuditLog.objects.create(
            user=user,
            action_type='LOGOUT',
            module_name='Security',
            record_id=user.username,
            description=f"User '{user.username}' logged out.",
            ip_address=ip,
        )
    except Exception as e:
        logger.warning(f'Failed to record logout audit: {e}')
