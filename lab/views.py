from core.access import RoleRequiredMixin
from core.choices import ROLE_LAB
from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)

from .forms import BloodTestForm
from .models import BloodTest


class BloodTestListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_LAB]
    model = BloodTest
    template_name = 'lab/list.html'
    select_related_fields = ['donation', 'donation__donor']
    fields = [
        ('Donation', 'donation'),
        ('ABO', 'abo_group'),
        ('Rh', 'rh_factor'),
        ('Hemoglobin', 'hemoglobin'),
        ('Result', 'overall_result'),
        ('Tested', 'tested_at'),
    ]
    search_fields = ['donation__donation_code', 'abo_group', 'overall_result']
    create_url_name = 'lab_add'
    edit_url_name = 'lab_edit'
    delete_url_name = 'lab_delete'
    page_title = 'Lab Testing'
    page_intro = 'Screen donated blood before it enters the blood bank.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for item, row in zip(context['items'], context['rows']):
            row['object'] = item
            row['failure_reasons'] = item.failure_reasons()
        return context


class BloodTestCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_LAB]
    model = BloodTest
    form_class = BloodTestForm
    success_url_name = 'lab_list'
    page_title = 'Add Blood Test'
    page_intro = 'Record lab findings for a donation.'


class BloodTestUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_LAB]
    model = BloodTest
    form_class = BloodTestForm
    success_url_name = 'lab_list'
    page_title = 'Edit Blood Test'
    page_intro = 'Correct or complete a test record.'


class BloodTestDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_LAB]
    model = BloodTest
    success_url_name = 'lab_list'
    page_title = 'Delete Blood Test'
    page_intro = 'Remove an incorrect test record.'
