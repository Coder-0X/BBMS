from core.crud import (
    BloodBankCreateView,
    BloodBankDeleteView,
    BloodBankListView,
    BloodBankUpdateView,
)

from .forms import BloodComponentForm, BloodUnitForm, InventoryForm
from .models import BloodComponent, BloodUnit, Inventory


class InventoryListView(BloodBankListView):
    model = Inventory
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


class ComponentListView(BloodBankListView):
    model = BloodComponent
    fields = [
        ('Name', 'component_name'),
        ('Description', 'description'),
    ]
    search_fields = ['component_name', 'description']
    create_url_name = 'component_add'
    edit_url_name = 'component_edit'
    delete_url_name = 'component_delete'
    page_title = 'Blood Components'
    page_intro = 'Define component types like plasma, platelets, and RBCs.'


class UnitListView(BloodBankListView):
    model = BloodUnit
    fields = [
        ('Code', 'unit_code'),
        ('Component', 'component'),
        ('Group', 'blood_group'),
        ('Rh', 'rh_factor'),
        ('Expiry', 'expiry_date'),
    ]
    search_fields = ['unit_code', 'blood_group', 'unit_state']
    create_url_name = 'unit_add'
    edit_url_name = 'unit_edit'
    delete_url_name = 'unit_delete'
    page_title = 'Blood Units'
    page_intro = 'Manage units by blood group, component, and expiry.'


class InventoryCreateView(BloodBankCreateView):
    model = Inventory
    form_class = InventoryForm
    success_url_name = 'inventory_list'
    page_title = 'Add Inventory Entry'
    page_intro = 'Add stock for a blood unit.'


class InventoryUpdateView(BloodBankUpdateView):
    model = Inventory
    form_class = InventoryForm
    success_url_name = 'inventory_list'
    page_title = 'Edit Inventory Entry'
    page_intro = 'Update quantities or storage state.'


class InventoryDeleteView(BloodBankDeleteView):
    model = Inventory
    success_url_name = 'inventory_list'
    page_title = 'Delete Inventory Entry'
    page_intro = 'Remove an inventory entry.'


class ComponentCreateView(BloodBankCreateView):
    model = BloodComponent
    form_class = BloodComponentForm
    success_url_name = 'component_list'
    page_title = 'Add Blood Component'
    page_intro = 'Create a new blood component type.'


class ComponentUpdateView(BloodBankUpdateView):
    model = BloodComponent
    form_class = BloodComponentForm
    success_url_name = 'component_list'
    page_title = 'Edit Blood Component'
    page_intro = 'Update component details.'


class ComponentDeleteView(BloodBankDeleteView):
    model = BloodComponent
    success_url_name = 'component_list'
    page_title = 'Delete Blood Component'
    page_intro = 'Remove a component type.'


class UnitCreateView(BloodBankCreateView):
    model = BloodUnit
    form_class = BloodUnitForm
    success_url_name = 'unit_list'
    page_title = 'Add Blood Unit'
    page_intro = 'Create a new blood unit record.'


class UnitUpdateView(BloodBankUpdateView):
    model = BloodUnit
    form_class = BloodUnitForm
    success_url_name = 'unit_list'
    page_title = 'Edit Blood Unit'
    page_intro = 'Update a blood unit record.'


class UnitDeleteView(BloodBankDeleteView):
    model = BloodUnit
    success_url_name = 'unit_list'
    page_title = 'Delete Blood Unit'
    page_intro = 'Remove a unit record.'
