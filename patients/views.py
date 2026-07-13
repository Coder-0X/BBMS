from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)

from .forms import (
    BloodIssueForm,
    BloodRequestForm,
    CrossmatchForm,
    PatientForm,
)
from .models import BloodIssue, BloodRequest, Crossmatch, Patient


class PatientListView(BloodBankListView):
    model = Patient
    fields = [
        ('Code', 'patient_code'),
        ('Name', 'full_name'),
        ('Gender', 'gender'),
        ('Age', 'age'),
        ('Diagnosis', 'diagnosis'),
    ]
    search_fields = ['patient_code', 'full_name', 'phone', 'diagnosis']
    create_url_name = 'patient_add'
    edit_url_name = 'patient_edit'
    delete_url_name = 'patient_delete'
    page_title = 'Patients'
    page_intro = 'Manage recipient profiles and clinical details.'


class PatientCreateView(BloodBankCreateView):
    model = Patient
    form_class = PatientForm
    success_url_name = 'patient_list'
    page_title = 'Add Patient'
    page_intro = 'Create a patient record.'


class PatientUpdateView(BloodBankUpdateView):
    model = Patient
    form_class = PatientForm
    success_url_name = 'patient_list'
    page_title = 'Edit Patient'
    page_intro = 'Update patient details.'


class PatientDeleteView(BloodBankDeleteView):
    model = Patient
    success_url_name = 'patient_list'
    page_title = 'Delete Patient'
    page_intro = 'Delete a patient record.'


class RequestListView(BloodBankListView):
    model = BloodRequest
    fields = [
        ('Code', 'request_code'),
        ('Patient', 'patient'),
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


class RequestCreateView(BloodBankCreateView):
    model = BloodRequest
    form_class = BloodRequestForm
    success_url_name = 'request_list'
    page_title = 'Add Blood Request'
    page_intro = 'Create a transfusion request.'


class RequestUpdateView(BloodBankUpdateView):
    model = BloodRequest
    form_class = BloodRequestForm
    success_url_name = 'request_list'
    page_title = 'Edit Blood Request'
    page_intro = 'Correct request data.'


class RequestDeleteView(BloodBankDeleteView):
    model = BloodRequest
    success_url_name = 'request_list'
    page_title = 'Delete Blood Request'
    page_intro = 'Remove a request record.'


class CrossmatchListView(BloodBankListView):
    model = Crossmatch
    fields = [
        ('Code', 'crossmatch_code'),
        ('Request', 'blood_request'),
        ('Result', 'compatibility_result'),
        ('Reserved Until', 'reserved_until'),
    ]
    search_fields = ['crossmatch_code', 'compatibility_result']
    create_url_name = 'crossmatch_add'
    edit_url_name = 'crossmatch_edit'
    delete_url_name = 'crossmatch_delete'
    page_title = 'Crossmatch'
    page_intro = 'Confirm compatibility before issuing blood.'


class CrossmatchCreateView(BloodBankCreateView):
    model = Crossmatch
    form_class = CrossmatchForm
    success_url_name = 'crossmatch_list'
    page_title = 'Add Crossmatch'
    page_intro = 'Create a compatibility record.'


class CrossmatchUpdateView(BloodBankUpdateView):
    model = Crossmatch
    form_class = CrossmatchForm
    success_url_name = 'crossmatch_list'
    page_title = 'Edit Crossmatch'
    page_intro = 'Update crossmatch results.'


class CrossmatchDeleteView(BloodBankDeleteView):
    model = Crossmatch
    success_url_name = 'crossmatch_list'
    page_title = 'Delete Crossmatch'
    page_intro = 'Remove a crossmatch record.'


class IssueListView(BloodBankListView):
    model = BloodIssue
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


class IssueCreateView(BloodBankCreateView):
    model = BloodIssue
    form_class = BloodIssueForm
    success_url_name = 'issue_list'
    page_title = 'Add Blood Issue'
    page_intro = 'Issue blood to a patient.'


class IssueUpdateView(BloodBankUpdateView):
    model = BloodIssue
    form_class = BloodIssueForm
    success_url_name = 'issue_list'
    page_title = 'Edit Blood Issue'
    page_intro = 'Update issue details.'


class IssueDeleteView(BloodBankDeleteView):
    model = BloodIssue
    success_url_name = 'issue_list'
    page_title = 'Delete Blood Issue'
    page_intro = 'Remove an issue record.'
