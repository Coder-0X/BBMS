from core.access import RoleRequiredMixin
from core.choices import ROLE_INVENTORY
from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)

from .forms import BloodComponentForm, BloodUnitForm, InventoryForm
from .models import BloodComponent, BloodUnit, Inventory
from .services import expire_units


class InventoryListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_INVENTORY]
    model = Inventory
    select_related_fields = [
        'blood_unit',
        'blood_unit__component',
        'blood_unit__donation',
        'blood_unit__donation__donor',
    ]
    fields = [
        ('Unit', 'blood_unit'),
        ('Available', 'available_quantity'),
        ('Reserved', 'reserved_quantity'),
        ('Location', 'location'),
        ('Status', 'storage_status'),
    ]
    search_fields = ['blood_unit__unit_code', 'location', 'storage_status']
    create_url_name = 'inventory_add'
    edit_url_name = 'inventory_edit'
    delete_url_name = 'inventory_delete'
    page_title = 'Inventory'
    page_intro = 'Track physical stock, reserved units, and storage state.'


class ComponentListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_INVENTORY]
    model = BloodComponent
    fields = [
        ('Name', 'component_name'),
        ('Shelf Life (days)', 'shelf_life_days'),
        ('mL / Unit', 'ml_per_unit'),
        ('Split %', 'split_percentage'),
        ('Active', 'is_active'),
    ]
    search_fields = ['component_name', 'description']
    create_url_name = 'component_add'
    edit_url_name = 'component_edit'
    delete_url_name = 'component_delete'
    page_title = 'Blood Components'
    page_intro = 'Define component types like plasma, platelets, and RBCs.'


class UnitListView(RoleRequiredMixin, BloodBankListView):
    allowed_roles = [ROLE_INVENTORY]
    model = BloodUnit
    template_name = 'inventory/unit_list.html'
    select_related_fields = ['component', 'donation', 'donation__donor']
    fields = [
        ('Code', 'unit_code'),
        ('Donation', 'donation'),
        ('Component', 'component'),
        ('Group', 'blood_group'),
        ('Rh', 'rh_factor'),
        ('Volume (mL)', 'quantity_ml'),
        ('Collected', 'collected_at'),
        ('Expiry', 'expiry_date'),
        ('State', 'unit_state'),
    ]
    search_fields = ['unit_code', 'blood_group', 'unit_state']
    create_url_name = 'unit_add'
    edit_url_name = 'unit_edit'
    delete_url_name = 'unit_delete'
    page_title = 'Blood Units'
    page_intro = 'Manage units by blood group, component, and expiry.'

    def get_queryset(self):
        # Keep unit_state honest on every visit to this screen instead of
        # relying solely on a cron job.
        expire_units()
        return super().get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for item, row in zip(context['items'], context['rows']):
            row['object'] = item
            row['units_available'] = item.units_available
            row['days_to_expiry'] = item.days_to_expiry
        return context


class InventoryCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_INVENTORY]
    model = Inventory
    form_class = InventoryForm
    success_url_name = 'inventory_list'
    page_title = 'Add Inventory Entry'
    page_intro = 'Add stock for a blood unit.'


class InventoryUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_INVENTORY]
    model = Inventory
    form_class = InventoryForm
    success_url_name = 'inventory_list'
    page_title = 'Edit Inventory Entry'
    page_intro = 'Update quantities or storage state.'


class InventoryDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_INVENTORY]
    model = Inventory
    success_url_name = 'inventory_list'
    page_title = 'Delete Inventory Entry'
    page_intro = 'Remove an inventory entry.'


class ComponentCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_INVENTORY]
    model = BloodComponent
    form_class = BloodComponentForm
    success_url_name = 'component_list'
    page_title = 'Add Blood Component'
    page_intro = 'Create a new blood component type.'


class ComponentUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_INVENTORY]
    model = BloodComponent
    form_class = BloodComponentForm
    success_url_name = 'component_list'
    page_title = 'Edit Blood Component'
    page_intro = 'Update component details.'


class ComponentDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_INVENTORY]
    model = BloodComponent
    success_url_name = 'component_list'
    page_title = 'Delete Blood Component'
    page_intro = 'Remove a component type.'


class UnitCreateView(RoleRequiredMixin, BloodBankCreateView):
    allowed_roles = [ROLE_INVENTORY]
    model = BloodUnit
    form_class = BloodUnitForm
    success_url_name = 'unit_list'
    page_title = 'Add Blood Unit'
    page_intro = 'Create a new blood unit record.'


class UnitUpdateView(RoleRequiredMixin, BloodBankUpdateView):
    allowed_roles = [ROLE_INVENTORY]
    model = BloodUnit
    form_class = BloodUnitForm
    success_url_name = 'unit_list'
    page_title = 'Edit Blood Unit'
    page_intro = 'Update a blood unit record.'


class UnitDeleteView(RoleRequiredMixin, BloodBankDeleteView):
    allowed_roles = [ROLE_INVENTORY]
    model = BloodUnit
    success_url_name = 'unit_list'
    page_title = 'Delete Blood Unit'
    page_intro = 'Remove a unit record.'
