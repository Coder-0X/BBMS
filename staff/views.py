from core.access import RoleRequiredMixin
from core.choices import ROLE_ADMIN
from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)

from .forms import AuditLogForm, StaffProfileForm
from .models import AuditLog, StaffProfile


class StaffListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_ADMIN]
    model = StaffProfile
    select_related_fields = ['user']
    fields = [
        ('Employee', 'employee_code'),
        ('User', 'user'),
        ('Role', 'get_role_display'),
        ('Phone', 'phone'),
    ]
    search_fields = ['employee_code', 'role', 'phone']
    create_url_name = 'staff_add'
    edit_url_name = 'staff_edit'
    delete_url_name = 'staff_delete'
    page_title = 'Staff Profiles'
    page_intro = 'Manage staff accounts and which section of the system each can access.'


class StaffCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_ADMIN]
    model = StaffProfile
    form_class = StaffProfileForm
    success_url_name = 'staff_list'
    page_title = 'Add Staff Profile'
    page_intro = 'Create a staff record and assign their access role.'


class StaffUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_ADMIN]
    model = StaffProfile
    form_class = StaffProfileForm
    success_url_name = 'staff_list'
    page_title = 'Edit Staff Profile'
    page_intro = 'Update staff details or change their role.'


class StaffDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_ADMIN]
    model = StaffProfile
    success_url_name = 'staff_list'
    page_title = 'Delete Staff Profile'
    page_intro = 'Remove a staff profile.'


class AuditLogListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_ADMIN]
    model = AuditLog
    template_name = 'staff/audit_list.html'
    select_related_fields = ['user']
    paginate_by = 50
    fields = [
        ('User', 'user'),
        ('Action', 'action_type'),
        ('Module', 'module_name'),
        ('Record', 'record_id'),
        ('Description', 'description'),
        ('IP Address', 'ip_address'),
        ('Created', 'created_at'),
    ]
    search_fields = ['action_type', 'module_name', 'description', 'record_id', 'user__username', 'ip_address']
    create_url_name = 'audit_add'
    edit_url_name = 'audit_edit'
    delete_url_name = 'audit_delete'
    page_title = 'Security & System Audit Trail'
    page_intro = 'Live automated compliance ledger tracking all user modifications, security events, and recall actions.'

    def get_queryset(self):
        qs = super().get_queryset()
        module_filter = self.request.GET.get('module', '').strip()
        if module_filter:
            qs = qs.filter(module_name=module_filter)

        action_filter = self.request.GET.get('action', '').strip()
        if action_filter:
            qs = qs.filter(action_type=action_filter)

        user_type = self.request.GET.get('user_type', '').strip()
        if user_type == 'staff':
            qs = qs.filter(user__isnull=False)
        elif user_type == 'system':
            qs = qs.filter(user__isnull=True)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        total_logs = AuditLog.objects.count()
        user_activity_count = AuditLog.objects.filter(user__isnull=False).count()
        system_activity_count = AuditLog.objects.filter(user__isnull=True).count()
        recall_count = AuditLog.objects.filter(action_type='RECALL').count()

        modules = (
            AuditLog.objects.values_list('module_name', flat=True)
            .distinct()
            .order_by('module_name')
        )
        actions = (
            AuditLog.objects.values_list('action_type', flat=True)
            .distinct()
            .order_by('action_type')
        )

        context.update({
            'total_logs': total_logs,
            'user_activity_count': user_activity_count,
            'system_activity_count': system_activity_count,
            'recall_count': recall_count,
            'modules': [m for m in modules if m],
            'actions': [a for a in actions if a],
            'selected_module': self.request.GET.get('module', '').strip(),
            'selected_action': self.request.GET.get('action', '').strip(),
            'selected_user_type': self.request.GET.get('user_type', '').strip(),
            'raw_items': context['items'],
        })
        return context


class AuditLogCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_ADMIN]
    model = AuditLog
    form_class = AuditLogForm
    success_url_name = 'audit_list'
    page_title = 'Add Audit Entry'
    page_intro = 'Record an operational event.'


class AuditLogUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_ADMIN]
    model = AuditLog
    form_class = AuditLogForm
    success_url_name = 'audit_list'
    page_title = 'Edit Audit Entry'
    page_intro = 'Adjust an audit note.'


class AuditLogDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_ADMIN]
    model = AuditLog
    success_url_name = 'audit_list'
    page_title = 'Delete Audit Entry'
    page_intro = 'Remove an audit record.'
