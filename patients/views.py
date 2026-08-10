import uuid

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from core.access import RoleRequiredMixin
from core.choices import ROLE_LAB, ROLE_TRANSFUSION
from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)
from inventory.models import BloodUnit

from . import services
from .forms import BloodIssueForm, BloodRequestForm, PatientForm
from .models import BloodIssue, BloodRequest, Crossmatch, Patient


class PatientListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = Patient
    fields = [
        ('Code', 'patient_code'),
        ('MRN', 'mrn'),
        ('Name', 'full_name'),
        ('Gender', 'gender'),
        ('Age', 'age'),
        ('Diagnosis', 'diagnosis'),
    ]
    search_fields = ['patient_code', 'mrn', 'full_name', 'phone', 'diagnosis']
    create_url_name = 'patient_add'
    edit_url_name = 'patient_edit'
    delete_url_name = 'patient_delete'
    page_title = 'Patients'
    page_intro = 'Manage recipient profiles and clinical details.'


class PatientCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = Patient
    form_class = PatientForm
    success_url_name = 'patient_list'
    page_title = 'Add Patient'
    page_intro = 'Create a patient record.'


class PatientUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = Patient
    form_class = PatientForm
    success_url_name = 'patient_list'
    page_title = 'Edit Patient'
    page_intro = 'Update patient details.'


class PatientDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = Patient
    success_url_name = 'patient_list'
    page_title = 'Delete Patient'
    page_intro = 'Delete a patient record.'


class RequestListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = BloodRequest
    template_name = 'patients/request_list.html'
    select_related_fields = ['patient', 'required_component']
    fields = [
        ('Code', 'request_code'),
        ('Patient', 'patient'),
        ('Group', 'required_blood_group'),
        ('Rh', 'required_rh'),
        ('Component', 'required_component'),
        ('Units', 'units_required'),
        ('Status', 'request_status'),
    ]
    search_fields = ['request_code', 'request_status', 'patient__full_name']
    create_url_name = 'request_add'
    edit_url_name = 'request_edit'
    delete_url_name = 'request_delete'
    page_title = 'Blood Requests'
    page_intro = 'Track incoming transfusion requests.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Attach the count of currently-available matching units to each
        # row so staff can see at a glance whether a request is matchable
        # before they click into it.
        for item, row in zip(context['items'], context['rows']):
            row['object'] = item
            row['match_count'] = services.matching_units_for_request(item).count()
        return context


class RequestCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = BloodRequest
    form_class = BloodRequestForm
    success_url_name = 'request_list'
    page_title = 'Add Blood Request'
    page_intro = 'Create a transfusion request.'


class RequestUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = BloodRequest
    form_class = BloodRequestForm
    success_url_name = 'request_list'
    page_title = 'Edit Blood Request'
    page_intro = 'Correct request data.'


class RequestDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = BloodRequest
    success_url_name = 'request_list'
    page_title = 'Delete Blood Request'
    page_intro = 'Remove a request record.'


class RequestMatchView(RoleRequiredMixin, View):
    """Step 1 of the crossmatch workflow: show every available unit that
    exactly matches a request's blood group, Rh and component, soonest
    expiry first, and let lab staff book one."""

    allowed_roles = [ROLE_LAB]
    template_name = 'patients/crossmatch_book.html'

    def get(self, request, pk):
        blood_request = get_object_or_404(BloodRequest, pk=pk)
        matches = services.matching_units_for_request(blood_request)
        incompatible_matches = services.incompatible_crossmatches_for_request(blood_request)
        return render(request, self.template_name, {
            'blood_request': blood_request,
            'matches': matches,
            'incompatible_matches': incompatible_matches,
            'page_title': 'Book a Crossmatch',
            'page_intro': (
                f'Available {blood_request.required_blood_group}'
                f'{blood_request.required_rh} '
                f'{blood_request.required_component} units in inventory, '
                'soonest expiry first.'
            ),
        })

    def post(self, request, pk):
        blood_request = get_object_or_404(BloodRequest, pk=pk)
        unit = get_object_or_404(
            BloodUnit, pk=request.POST.get('unit_id'), unit_state='Available',
        )
        crossmatch_code = f'CM-{uuid.uuid4().hex[:8].upper()}'
        services.book_unit(blood_request, unit, crossmatch_code)
        messages.success(
            request,
            f'{unit.unit_code} booked and reserved for 48 hours against '
            f'{blood_request.request_code}. Record the crossmatch test '
            'result to approve or reject it.',
        )
        return redirect('crossmatch_list')


class RequestPickView(RoleRequiredMixin, View):
    """Entry point for 'Add Crossmatch': choose which pending request to
    book a unit against."""

    allowed_roles = [ROLE_LAB]
    template_name = 'patients/crossmatch_pick_request.html'

    def get(self, request):
        pending_requests = BloodRequest.objects.filter(
            request_status='Pending',
        )
        return render(request, self.template_name, {
            'pending_requests': pending_requests,
            'page_title': 'Book a Crossmatch',
            'page_intro': 'Pick the request you want to reserve blood for.',
        })


class CrossmatchListView(RoleRequiredMixin, BloodBankListView):
    # Both lab (who book/test) and transfusion (who issue afterwards)
    # staff need visibility into crossmatch status.
    allowed_roles = [ROLE_LAB, ROLE_TRANSFUSION]
    model = Crossmatch
    template_name = 'patients/crossmatch_list.html'
    select_related_fields = [
        'blood_request',
        'blood_request__patient',
        'blood_request__required_component',
        'blood_unit',
        'blood_unit__component',
    ]
    fields = [
        ('Code', 'crossmatch_code'),
        ('Request', 'blood_request'),
        ('Unit', 'blood_unit'),
        ('Status', 'crossmatch_status'),
        ('Compatibility', 'compatibility_result'),
        ('Reserved Until', 'reserved_until'),
    ]
    search_fields = ['crossmatch_code', 'compatibility_result', 'crossmatch_status']
    create_url_name = 'crossmatch_add'
    edit_url_name = 'crossmatch_edit'
    delete_url_name = 'crossmatch_delete'
    page_title = 'Crossmatch'
    page_intro = 'Confirm compatibility before issuing blood.'

    def get_queryset(self):
        # Sweep for anything that has quietly passed its 48h reservation
        # window every time this list is viewed, so the screen never
        # shows a stale "Booked" row that should have been released.
        services.release_expired_crossmatches()
        return super().get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for item, row in zip(context['items'], context['rows']):
            row['object'] = item
        # Only lab staff can book new crossmatches or record test results;
        # transfusion staff get a read-only view of this screen.
        from core.access import get_staff_role
        role = get_staff_role(self.request.user)
        context['can_manage_crossmatch'] = role in (ROLE_LAB, 'Admin')
        context['can_issue'] = role in (ROLE_TRANSFUSION, 'Admin')
        return context


class CrossmatchDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_LAB]
    model = Crossmatch
    success_url_name = 'crossmatch_list'
    page_title = 'Delete Crossmatch'
    page_intro = 'Remove a crossmatch record.'


class CrossmatchTestView(RoleRequiredMixin, View):
    """Step 2 of the crossmatch workflow: lab records the physical
    compatibility test result. Compatible approves the unit for issue,
    Incompatible releases it straight back to available inventory."""

    allowed_roles = [ROLE_LAB]
    template_name = 'patients/crossmatch_test.html'

    def get(self, request, pk):
        crossmatch = get_object_or_404(Crossmatch, pk=pk)
        return render(request, self.template_name, {
            'crossmatch': crossmatch,
            'page_title': 'Record Crossmatch Test',
            'page_intro': 'Enter the compatibility test outcome for this booked unit.',
        })

    def post(self, request, pk):
        crossmatch = get_object_or_404(Crossmatch, pk=pk)
        if crossmatch.crossmatch_status != 'Booked':
            messages.warning(request, 'This crossmatch has already been resolved.')
            return redirect('crossmatch_list')

        result = request.POST.get('result')
        is_compatible = result == 'Compatible'
        services.record_compatibility_result(crossmatch, is_compatible)

        if is_compatible:
            messages.success(
                request,
                f'{crossmatch.blood_unit.unit_code} passed crossmatch and '
                'is approved for issue.',
            )
        else:
            messages.warning(
                request,
                f'{crossmatch.blood_unit.unit_code} failed crossmatch and '
                'was released back to available inventory. '
                f'{crossmatch.blood_request.request_code} is pending again.',
            )
        return redirect('crossmatch_list')


class IssueListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = BloodIssue
    select_related_fields = [
        'crossmatch',
        'crossmatch__blood_unit',
        'crossmatch__blood_unit__component',
        'issued_to_patient',
    ]
    fields = [
        ('Code', 'issue_code'),
        ('Crossmatch', 'crossmatch'),
        ('Patient', 'issued_to_patient'),
        ('Doctor', 'doctor_name'),
        ('Status', 'issue_status'),
    ]
    search_fields = [
        'issue_code',
        'doctor_name',
        'hospital_name',
        'issue_status',
    ]
    create_url_name = 'issue_add'
    edit_url_name = 'issue_edit'
    delete_url_name = 'issue_delete'
    page_title = 'Blood Issues'
    page_intro = 'Monitor issued blood and fulfillment status.'


class IssueCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = BloodIssue
    form_class = BloodIssueForm
    success_url_name = 'issue_list'
    page_title = 'Add Blood Issue'
    page_intro = 'Issue blood to a patient. Only crossmatches that passed are selectable.'

    def form_valid(self, form):
        response = super().form_valid(form)
        services.issue_unit(self.object.crossmatch)
        messages.success(
            self.request,
            f'{self.object.crossmatch.blood_unit.unit_code} issued to '
            f'{self.object.issued_to_patient}.',
        )
        return response


class IssueUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = BloodIssue
    form_class = BloodIssueForm
    success_url_name = 'issue_list'
    page_title = 'Edit Blood Issue'
    page_intro = 'Update issue details.'


class IssueDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_TRANSFUSION]
    model = BloodIssue
    success_url_name = 'issue_list'
    page_title = 'Delete Blood Issue'
    page_intro = 'Remove an issue record.'
