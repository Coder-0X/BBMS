from core.access import RoleRequiredMixin
from core.choices import (
    ROLE_ADMIN,
    ROLE_BOOTH,
    ROLE_LAB,
    ROLE_TRANSFUSION,
)
from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)

from .forms import DonationForm, DonorForm
from .models import Donation, Donor


class DonorListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_BOOTH]
    model = Donor
    fields = [
        ('Code', 'donor_code'),
        ('Name', 'full_name'),
        ('Blood Group', 'blood_group'),
        ('Rh', 'rh_factor'),
        ('Phone', 'phone'),
        ('Email', 'email'),
    ]
    search_fields = ['donor_code', 'full_name', 'blood_group', 'phone', 'email']
    create_url_name = 'donor_add'
    edit_url_name = 'donor_edit'
    delete_url_name = 'donor_delete'
    page_title = 'Donors'
    page_intro = 'Register donors and manage blood donation history.'


class DonorCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_BOOTH]
    model = Donor
    form_class = DonorForm
    success_url_name = 'donor_list'
    page_title = 'Add Donor'
    page_intro = 'Create a donor profile with contact and blood details.'


class DonorUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_BOOTH]
    model = Donor
    form_class = DonorForm
    success_url_name = 'donor_list'
    page_title = 'Edit Donor'
    page_intro = 'Update donor profile details.'


class DonorDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_BOOTH]
    model = Donor
    success_url_name = 'donor_list'
    page_title = 'Delete Donor'
    page_intro = 'Remove a donor record when it is no longer needed.'


class DonationListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_BOOTH]
    model = Donation
    template_name = 'donors/donation_list.html'
    select_related_fields = ['donor']
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for item, row in zip(context['items'], context['rows']):
            row['object'] = item
        return context


class DonationCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_BOOTH]
    model = Donation
    form_class = DonationForm
    success_url_name = 'donation_list'
    page_title = 'Add Donation'
    page_intro = 'Record a collected donation.'


class DonationUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_BOOTH]
    model = Donation
    form_class = DonationForm
    success_url_name = 'donation_list'
    page_title = 'Edit Donation'
    page_intro = 'Adjust donation data when needed.'


class DonationDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_BOOTH]
    model = Donation
    success_url_name = 'donation_list'
    page_title = 'Delete Donation'
    page_intro = 'Delete an incorrect donation record.'


class DonorRecallSearchView(RoleRequiredMixin, BloodBankListView):
    """Search and lookup page for donor safety recalls, post-donation infection
    tracking (e.g. HIV/Hepatitis), and inventory lookback.
    """
    allowed_roles = [ROLE_BOOTH, ROLE_LAB, ROLE_TRANSFUSION, ROLE_ADMIN]
    model = Donor
    template_name = 'donors/donor_recall_search.html'
    page_title = 'Donor Safety Recall & Lookback'
    page_intro = 'Investigate post-donation infection reports, trace transfused recipients, and destroy infected units in stock.'
    search_fields = ['donor_code', 'full_name', 'phone', 'email', 'deferral_reason']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from inventory.models import BloodUnit
        from patients.models import BloodIssue

        donors_with_meta = []
        for donor in context.get('items', []):
            donor_units = BloodUnit.objects.filter(donation__donor=donor)
            in_stock_count = donor_units.filter(unit_state__in=['Available', 'Reserved', 'Quarantined']).count()
            issued_count = BloodIssue.objects.filter(crossmatch__blood_unit__donation__donor=donor).count()
            donations_count = donor.donation_set.count()
            donors_with_meta.append({
                'donor': donor,
                'in_stock_count': in_stock_count,
                'issued_count': issued_count,
                'donations_count': donations_count,
            })
        context['donors_with_meta'] = donors_with_meta
        return context


class DonorRecallDetailView(RoleRequiredMixin, BloodBankListView):
    """Detailed lookback trace and emergency stock disposal dashboard for a specific donor."""
    allowed_roles = [ROLE_BOOTH, ROLE_LAB, ROLE_TRANSFUSION, ROLE_ADMIN]
    template_name = 'donors/donor_recall_detail.html'
    model = Donor

    def get(self, request, *args, **kwargs):
        from django.shortcuts import get_object_or_404, render
        from inventory.models import BloodUnit
        from patients.models import BloodIssue

        donor = get_object_or_404(Donor, pk=kwargs.get('pk'))
        donations = donor.donation_set.all().order_by('-donation_datetime')
        all_units = BloodUnit.objects.filter(donation__donor=donor).select_related('component', 'donation').order_by('-collected_at')
        
        in_stock_units = all_units.filter(unit_state__in=['Available', 'Reserved', 'Quarantined'])
        discarded_units = all_units.filter(unit_state__in=['Discarded', 'Expired'])
        
        # Recipients who received blood from this donor
        transfused_issues = BloodIssue.objects.filter(
            crossmatch__blood_unit__donation__donor=donor
        ).select_related(
            'crossmatch__blood_unit__component',
            'crossmatch__blood_request',
            'issued_to_patient'
        ).order_by('-issued_datetime')

        context = {
            'donor': donor,
            'donations': donations,
            'all_units': all_units,
            'in_stock_units': in_stock_units,
            'discarded_units': discarded_units,
            'transfused_issues': transfused_issues,
            'page_title': f'Safety Recall Trace: {donor.donor_code} ({donor.full_name})',
            'page_intro': 'Full audit trail of all donations, split component units, in-stock inventory, and transfused patients.',
        }
        return render(request, self.template_name, context)


class DonorRecallDestroyStockView(RoleRequiredMixin, BloodBankCreateView):
    """Emergency POST action: immediately destroy/discard all in-stock units
    for a recalled donor and flag them as permanently deferred.
    """
    allowed_roles = [ROLE_BOOTH, ROLE_LAB, ROLE_TRANSFUSION, ROLE_ADMIN]

    def post(self, request, *args, **kwargs):
        from django.contrib import messages
        from django.db import transaction
        from django.shortcuts import get_object_or_404, redirect
        from inventory.models import BloodUnit, Inventory
        from patients.models import Crossmatch
        from staff.models import AuditLog

        donor = get_object_or_404(Donor, pk=kwargs.get('pk'))
        reason = request.POST.get('deferral_reason') or 'Post-donation infection reported (e.g. HIV/Hepatitis)'

        with transaction.atomic():
            # 1. Flag donor as permanently deferred
            donor.is_deferred = True
            donor.deferral_reason = reason
            donor.save()

            # 2. Find all in-stock blood units
            in_stock = BloodUnit.objects.filter(
                donation__donor=donor,
                unit_state__in=['Available', 'Reserved', 'Quarantined'],
            )
            destroyed_count = in_stock.count()
            destroyed_codes = list(in_stock.values_list('unit_code', flat=True))

            # 3. Discard all units and release crossmatches
            for unit in in_stock:
                unit.unit_state = 'Discarded'
                unit.save()

                # Update matching inventory record
                Inventory.objects.filter(blood_unit=unit).update(
                    storage_status='Discarded',
                    available_quantity=0,
                    reserved_quantity=0,
                )

                # Release any active crossmatches on this unit
                Crossmatch.objects.filter(
                    blood_unit=unit,
                    crossmatch_status__in=['Booked', 'Passed']
                ).update(crossmatch_status='Released')

            # 4. Log emergency recall action in AuditLog
            AuditLog.objects.create(
                user=request.user,
                action_type='RECALL',
                module_name='Donors',
                record_id=donor.donor_code,
                description=(
                    f"EMERGENCY RECALL EXECUTED: Donor {donor.donor_code} ({donor.full_name}) "
                    f"flagged as deferred. Reason: '{reason}'. Destroyed {destroyed_count} in-stock units: "
                    f"{', '.join(destroyed_codes) if destroyed_codes else 'None in stock'}. "
                    f"Recipient lookback active for any prior transfusions."
                ),
                ip_address=request.META.get('REMOTE_ADDR'),
            )

        messages.warning(
            request,
            f"Emergency Safety Recall Executed: {destroyed_count} in-stock blood unit(s) were successfully destroyed and marked 'Discarded'. Donor {donor.donor_code} has been permanently deferred.",
        )
        return redirect('donor_recall_detail', pk=donor.pk)
