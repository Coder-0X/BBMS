from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)

from .forms import DonationForm, DonorForm
from .models import Donation, Donor


class DonorListView(BloodBankListView):
    model = Donor
    fields = [
        ('Code', 'donor_code'),
        ('Name', 'full_name'),
        ('Blood Group', 'blood_group'),
        ('Rh', 'rh_factor'),
        ('Phone', 'phone'),
    ]
    search_fields = ['donor_code', 'full_name', 'blood_group', 'phone']
    create_url_name = 'donor_add'
    edit_url_name = 'donor_edit'
    delete_url_name = 'donor_delete'
    page_title = 'Donors'
    page_intro = 'Register donors and manage blood donation history.'


class DonorCreateView(BloodBankCreateView):
    model = Donor
    form_class = DonorForm
    success_url_name = 'donor_list'
    page_title = 'Add Donor'
    page_intro = 'Create a donor profile with contact and blood details.'


class DonorUpdateView(BloodBankUpdateView):
    model = Donor
    form_class = DonorForm
    success_url_name = 'donor_list'
    page_title = 'Edit Donor'
    page_intro = 'Update donor profile details.'


class DonorDeleteView(BloodBankDeleteView):
    model = Donor
    success_url_name = 'donor_list'
    page_title = 'Delete Donor'
    page_intro = 'Remove a donor record when it is no longer needed.'


class DonationListView(BloodBankListView):
    model = Donation
    fields = [
        ('Code', 'donation_code'),
        ('Donor', 'donor'),
        ('Date/Time', 'donation_datetime'),
        ('Quantity ML', 'quantity_ml'),
        ('Status', 'status'),
    ]
    search_fields = ['donation_code', 'status', 'donor__full_name']
    create_url_name = 'donation_add'
    edit_url_name = 'donation_edit'
    delete_url_name = 'donation_delete'
    page_title = 'Donations'
    page_intro = 'Track blood donations from intake through collection.'


class DonationCreateView(BloodBankCreateView):
    model = Donation
    form_class = DonationForm
    success_url_name = 'donation_list'
    page_title = 'Add Donation'
    page_intro = 'Record a collected donation.'


class DonationUpdateView(BloodBankUpdateView):
    model = Donation
    form_class = DonationForm
    success_url_name = 'donation_list'
    page_title = 'Edit Donation'
    page_intro = 'Adjust donation data when needed.'


class DonationDeleteView(BloodBankDeleteView):
    model = Donation
    success_url_name = 'donation_list'
    page_title = 'Delete Donation'
    page_intro = 'Delete an incorrect donation record.'
