from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)

from .forms import BloodTestForm
from .models import BloodTest


class BloodTestListView(BloodBankListView):
    model = BloodTest
    fields = [
        ('Donation', 'donation'),
        ('ABO', 'abo_group'),
        ('Rh', 'rh_factor'),
        ('Result', 'overall_result'),
        ('Tested', 'tested_at'),
    ]
    search_fields = ['donation__donation_code', 'abo_group', 'overall_result']
    create_url_name = 'lab_add'
    edit_url_name = 'lab_edit'
    delete_url_name = 'lab_delete'
    page_title = 'Lab Testing'
    page_intro = 'Screen donated blood before it enters the blood bank.'


class BloodTestCreateView(BloodBankCreateView):
    model = BloodTest
    form_class = BloodTestForm
    success_url_name = 'lab_list'
    page_title = 'Add Blood Test'
    page_intro = 'Record lab findings for a donation.'


class BloodTestUpdateView(BloodBankUpdateView):
    model = BloodTest
    form_class = BloodTestForm
    success_url_name = 'lab_list'
    page_title = 'Edit Blood Test'
    page_intro = 'Correct or complete a test record.'


class BloodTestDeleteView(BloodBankDeleteView):
    model = BloodTest
    success_url_name = 'lab_list'
    page_title = 'Delete Blood Test'
    page_intro = 'Remove an incorrect test record.'
