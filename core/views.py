import json
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from core.choices import ABO_CHOICES, RH_CHOICES
from donors.models import Donation, Donor
from inventory.models import BloodComponent, BloodUnit, Inventory
from lab.models import BloodTest
from patients.models import BloodIssue, BloodRequest, Crossmatch, Patient
from staff.models import AuditLog, StaffProfile


@login_required
def dashboard(request):
    modules = [
        {'label': 'Donors', 'count': Donor.objects.count(), 'url': 'donor_list', 'icon': 'fa-hand-holding-heart'},
        {'label': 'Donations', 'count': Donation.objects.count(), 'url': 'donation_list', 'icon': 'fa-tint'},
        {'label': 'Lab Tests', 'count': BloodTest.objects.count(), 'url': 'lab_list', 'icon': 'fa-flask'},
        {'label': 'Blood Units', 'count': BloodUnit.objects.count(), 'url': 'unit_list', 'icon': 'fa-box-open'},
        {'label': 'Inventory', 'count': Inventory.objects.count(), 'url': 'inventory_list', 'icon': 'fa-boxes'},
        {'label': 'Patients', 'count': Patient.objects.count(), 'url': 'patient_list', 'icon': 'fa-user-injured'},
        {'label': 'Requests', 'count': BloodRequest.objects.count(), 'url': 'request_list', 'icon': 'fa-file-medical'},
        {'label': 'Crossmatches', 'count': Crossmatch.objects.count(), 'url': 'crossmatch_list', 'icon': 'fa-balance-scale'},
        {'label': 'Issues', 'count': BloodIssue.objects.count(), 'url': 'issue_list', 'icon': 'fa-procedures'},
        {'label': 'Staff Profiles', 'count': StaffProfile.objects.count(), 'url': 'staff_list', 'icon': 'fa-id-badge'},
        {'label': 'Audit Logs', 'count': AuditLog.objects.count(), 'url': 'audit_list', 'icon': 'fa-shield-alt'},
    ]

    # --- Blood Group Distribution (Available Stock) ---
    all_groups = [f"{g[0]}{r[0]}" for g in ABO_CHOICES for r in RH_CHOICES]
    group_counts = {g: 0 for g in all_groups}

    available_units = BloodUnit.objects.filter(unit_state='Available')
    for unit in available_units.values('blood_group', 'rh_factor').annotate(total=Count('id')):
        key = f"{unit['blood_group']}{unit['rh_factor']}"
        if key in group_counts:
            group_counts[key] = unit['total']

    # --- Component Type Distribution ---
    component_stats = (
        BloodUnit.objects.filter(unit_state='Available')
        .values('component__component_name')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    component_labels = [c['component__component_name'] or 'Unknown' for c in component_stats]
    component_data = [c['total'] for c in component_stats]

    # --- Stock & Pipeline Health Alerts ---
    today = timezone.localdate()
    expiring_soon_units = (
        BloodUnit.objects.filter(
            unit_state='Available',
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=7),
        )
        .select_related('component')
        .order_by('expiry_date')[:5]
    )

    pending_requests = (
        BloodRequest.objects.filter(request_status='Pending')
        .select_related('patient', 'required_component')
        .order_by('-request_date')[:5]
    )

    total_available = BloodUnit.objects.filter(unit_state='Available').count()
    total_reserved = BloodUnit.objects.filter(unit_state='Reserved').count()
    total_expired = BloodUnit.objects.filter(unit_state='Expired').count()

    context = {
        'modules': modules,
        'group_labels_json': json.dumps(list(group_counts.keys())),
        'group_counts_json': json.dumps(list(group_counts.values())),
        'component_labels_json': json.dumps(component_labels),
        'component_data_json': json.dumps(component_data),
        'expiring_soon_units': expiring_soon_units,
        'pending_requests': pending_requests,
        'total_available': total_available,
        'total_reserved': total_reserved,
        'total_expired': total_expired,
    }

    return render(request, 'dashboard.html', context)

