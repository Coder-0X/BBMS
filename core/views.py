from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from donors.models import Donation, Donor
from inventory.models import BloodUnit, Inventory
from lab.models import BloodTest
from patients.models import BloodIssue, BloodRequest, Crossmatch, Patient
from staff.models import AuditLog, StaffProfile


@login_required
def dashboard(request):
    modules = [
        {'label': 'Donors', 'count': Donor.objects.count()},
        {'label': 'Donations', 'count': Donation.objects.count()},
        {'label': 'Lab Tests', 'count': BloodTest.objects.count()},
        {'label': 'Blood Units', 'count': BloodUnit.objects.count()},
        {'label': 'Inventory Rows', 'count': Inventory.objects.count()},
        {'label': 'Patients', 'count': Patient.objects.count()},
        {'label': 'Requests', 'count': BloodRequest.objects.count()},
        {'label': 'Crossmatches', 'count': Crossmatch.objects.count()},
        {'label': 'Issues', 'count': BloodIssue.objects.count()},
        {'label': 'Staff Profiles', 'count': StaffProfile.objects.count()},
        {'label': 'Audit Logs', 'count': AuditLog.objects.count()},
    ]
    quick_actions = [
        {'label': 'Add Donor', 'url': 'donor_add'},
        {'label': 'Add Donation', 'url': 'donation_add'},
        {'label': 'Add Lab Test', 'url': 'lab_add'},
        {'label': 'Add Request', 'url': 'request_add'},
        {'label': 'Add Issue', 'url': 'issue_add'},
    ]
    return render(
        request,
        'dashboard.html',
        {'modules': modules, 'quick_actions': quick_actions},
    )
