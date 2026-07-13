from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)

from .forms import AuditLogForm, StaffProfileForm
from .models import AuditLog, StaffProfile


class StaffListView(BloodBankListView):
    model = StaffProfile
    fields = [
        ('Employee', 'employee_code'),
        ('User', 'user'),
        ('Role', 'role_name'),
        ('Phone', 'phone'),
    ]
    search_fields = ['employee_code', 'role_name', 'phone']
    create_url_name = 'staff_add'
    edit_url_name = 'staff_edit'
    delete_url_name = 'staff_delete'
    page_title = 'Staff Profiles'
    page_intro = 'Manage staff accounts and operational roles.'


class StaffCreateView(BloodBankCreateView):
    model = StaffProfile
    form_class = StaffProfileForm
    success_url_name = 'staff_list'
    page_title = 'Add Staff Profile'
    page_intro = 'Create a staff record.'


class StaffUpdateView(BloodBankUpdateView):
    model = StaffProfile
    form_class = StaffProfileForm
    success_url_name = 'staff_list'
    page_title = 'Edit Staff Profile'
    page_intro = 'Update staff details.'


class StaffDeleteView(BloodBankDeleteView):
    model = StaffProfile
    success_url_name = 'staff_list'
    page_title = 'Delete Staff Profile'
    page_intro = 'Remove a staff profile.'


class AuditLogListView(BloodBankListView):
    model = AuditLog
    fields = [
        ('Action', 'action_type'),
        ('Module', 'module_name'),
        ('Record', 'record_id'),
        ('Created', 'created_at'),
    ]
    search_fields = ['action_type', 'module_name', 'description']
    create_url_name = 'audit_add'
    edit_url_name = 'audit_edit'
    delete_url_name = 'audit_delete'
    page_title = 'Audit Log'
    page_intro = 'Review actions captured across the system.'


class AuditLogCreateView(BloodBankCreateView):
    model = AuditLog
    form_class = AuditLogForm
    success_url_name = 'audit_list'
    page_title = 'Add Audit Entry'
    page_intro = 'Record an operational event.'


class AuditLogUpdateView(BloodBankUpdateView):
    model = AuditLog
    form_class = AuditLogForm
    success_url_name = 'audit_list'
    page_title = 'Edit Audit Entry'
    page_intro = 'Adjust an audit note.'


class AuditLogDeleteView(BloodBankDeleteView):
    model = AuditLog
    success_url_name = 'audit_list'
    page_title = 'Delete Audit Entry'
    page_intro = 'Remove an audit record.'
