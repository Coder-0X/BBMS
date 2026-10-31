"""
Shared fixtures and factories for the entire test suite.
"""
import uuid
import pytest
from datetime import timedelta
from django.utils import timezone
import factory
from factory.django import DjangoModelFactory


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_COMPONENT_TYPE_DEFAULTS = {
    'RBC':  ('RBC_STD', 'Red Blood Cells Standard', 1008, 1.0, 6.0),
    'FFP':  ('FFP_STD', 'Fresh Frozen Plasma Standard', 8760, -25.0, -18.0),
    'PLT':  ('PLT_STD', 'Platelets Standard', 168, 20.0, 24.0),
    'CRYO': ('CRYO_STD', 'Cryoprecipitate Standard', 8760, -25.0, -18.0),
    'WB':   ('WB_STD', 'Whole Blood Standard', 504, 1.0, 6.0),
    'GRAN': ('GRAN_STD', 'Granulocytes Standard', 24, 20.0, 24.0),
}


def _get_or_create_component_type(component_class):
    from inventory.models import ComponentType
    defaults = _COMPONENT_TYPE_DEFAULTS.get(component_class, _COMPONENT_TYPE_DEFAULTS['RBC'])
    code, name, shelf_life, temp_min, temp_max = defaults
    obj, _ = ComponentType.objects.get_or_create(
        code=code,
        defaults={
            'name': name,
            'component_class': component_class,
            'shelf_life_hours': shelf_life,
            'storage_temp_min_c': temp_min,
            'storage_temp_max_c': temp_max,
        }
    )
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# Factories
# ─────────────────────────────────────────────────────────────────────────────

class BranchFactory(DjangoModelFactory):
    class Meta:
        model = 'core.Branch'

    name = factory.Sequence(lambda n: f'Branch {n}')
    facility_code = factory.Sequence(
        lambda n: chr(65 + n % 26) + chr(65 + (n // 26) % 26) + chr(65 + (n // 676) % 26)
    )


class UserFactory(DjangoModelFactory):
    class Meta:
        model = 'accounts.User'

    username = factory.Sequence(lambda n: f'user{n}')
    display_name = factory.Sequence(lambda n: f'Test User {n}')
    branch = factory.SubFactory(BranchFactory)
    is_active = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        kwargs.setdefault('password', 'testpass123')
        manager = cls._get_manager(model_class)
        return manager.create_user(**kwargs)


class SubjectIdentityFactory(DjangoModelFactory):
    class Meta:
        model = 'privacy.SubjectIdentity'

    subject_type = 'donor'
    created_by = factory.SubFactory(UserFactory)

    @factory.post_generation
    def _encrypt_name(obj, create, extracted, **kwargs):
        if create and not obj.name_enc:
            from privacy.vault import encrypt, blind_index
            name = f'Test Subject {obj.pk}'
            obj.name_enc = encrypt(name)
            obj.name_blind_index = blind_index(name)
            obj.save(update_fields=['name_enc', 'name_blind_index'])


class ConsentRecordFactory(DjangoModelFactory):
    class Meta:
        model = 'privacy.ConsentRecord'

    subject = factory.SubFactory(SubjectIdentityFactory)
    subject_type = 'donor'
    purpose = 'Blood donation and processing'
    lawful_basis = 'consent'
    notice_version = '1.0'
    captured_by = factory.SubFactory(UserFactory)


class DonorFactory(DjangoModelFactory):
    class Meta:
        model = 'donors.Donor'

    subject = factory.SubFactory(SubjectIdentityFactory, subject_type='donor')
    sex = 'M'
    dob = factory.LazyFunction(lambda: timezone.now().date().replace(year=1985))
    blood_group_abo = 'O'
    blood_group_rh = 'pos'
    deferral_status = 'active'
    registration_branch = factory.SubFactory(BranchFactory)
    created_by = factory.SubFactory(UserFactory)


class DonationFactory(DjangoModelFactory):
    class Meta:
        model = 'donors.Donation'

    donor = factory.SubFactory(DonorFactory)
    branch = factory.LazyAttribute(lambda o: o.donor.registration_branch)
    donated_at = factory.LazyFunction(timezone.now)
    donation_type = 'whole_blood'
    collected_by = factory.SubFactory(UserFactory)
    consent = factory.SubFactory(ConsentRecordFactory,
                                 subject=factory.SelfAttribute('..donor.subject'))


class BloodUnitFactory(DjangoModelFactory):
    class Meta:
        model = 'inventory.BloodUnit'

    donation = factory.SubFactory(DonationFactory)
    parent_donation = factory.LazyAttribute(lambda o: o.donation)
    did = factory.Sequence(lambda n: f'{n:012d}')
    did_check_char = '0'
    component_class = 'RBC'
    component_type = factory.LazyAttribute(lambda o: _get_or_create_component_type(o.component_class))
    abo_type = 'O'
    rh_d_type = 'neg'
    status = 'available'
    owner_branch = factory.SubFactory(BranchFactory)
    collection_datetime = factory.LazyFunction(
        lambda: timezone.now() - timedelta(days=1)
    )
    expiry_datetime = factory.LazyFunction(
        lambda: timezone.now() + timedelta(days=42)
    )
    collected_by = factory.SubFactory(UserFactory)


class PatientFactory(DjangoModelFactory):
    class Meta:
        model = 'patients.Patient'

    subject = factory.SubFactory(SubjectIdentityFactory, subject_type='patient')
    sex = 'M'
    created_by = factory.SubFactory(UserFactory)


class PatientBloodGroupFactory(DjangoModelFactory):
    class Meta:
        model = 'patients.PatientBloodGroup'

    patient = factory.SubFactory(PatientFactory)
    branch = factory.SubFactory(BranchFactory)
    abo = 'O'
    rh_d = 'neg'
    method = 'tube'
    determined_by = factory.SubFactory(UserFactory)
    determined_at = factory.LazyFunction(timezone.now)
    is_discrepant = False


class BloodRequestFactory(DjangoModelFactory):
    class Meta:
        model = 'transfusion.BloodRequest'

    patient = factory.SubFactory(PatientFactory)
    branch = factory.SubFactory(BranchFactory)
    component_class = 'RBC'
    units_requested = 1
    urgency = 'routine'
    requesting_physician = factory.SubFactory(UserFactory)


class ReagentFactory(DjangoModelFactory):
    class Meta:
        model = 'quality.Reagent'

    name = factory.Sequence(lambda n: f'Anti-A reagent {n}')
    category = 'grouping'
    reagent_code = factory.Sequence(lambda n: f'RGT{n:04d}')
    manufacturer = 'TestMfr'
    qc_interval_hours = 24
    minimum_lots = 2
    active = True


class ReagentLotFactory(DjangoModelFactory):
    class Meta:
        model = 'quality.ReagentLot'

    reagent = factory.SubFactory(ReagentFactory)
    lot_number = factory.Sequence(lambda n: f'LOT{n:06d}')
    expiry_date = factory.LazyFunction(lambda: timezone.now().date() + timedelta(days=180))
    received_at = factory.LazyFunction(lambda: timezone.now().date())
    received_by = factory.SubFactory(UserFactory)
    branch = factory.SubFactory(BranchFactory)
    status = 'in_use'
    certificate_ok = True


class NonConformanceFactory(DjangoModelFactory):
    class Meta:
        model = 'quality.NonConformance'

    nc_type = 'labelling'
    severity = 'minor'
    status = 'open'
    description = 'Test NC description'
    event_date = factory.LazyFunction(lambda: timezone.now().date())
    reported_by = factory.SubFactory(UserFactory)
    branch = factory.SubFactory(BranchFactory)


class StorageEquipmentFactory(DjangoModelFactory):
    class Meta:
        model = 'coldchain.StorageEquipment'

    name = factory.Sequence(lambda n: f'Fridge {n}')
    equipment_type = 'refrigerator'
    sensor_id = factory.Sequence(lambda n: f'SENSOR{n:04d}')
    branch = factory.SubFactory(BranchFactory)
    component_class_allowed = 'RBC'
    status = 'active'


# ─────────────────────────────────────────────────────────────────────────────
# Shared pytest fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def branch(db):
    return BranchFactory()


@pytest.fixture
def user(db, branch):
    return UserFactory(branch=branch)


@pytest.fixture
def donor(db, branch, user):
    return DonorFactory(registration_branch=branch, created_by=user)


@pytest.fixture
def available_o_neg_rbc(db, branch, donor):
    """A crossmatch-ready O-negative RBC unit."""
    donation = DonationFactory(donor=donor, branch=branch)
    return BloodUnitFactory(
        donation=donation,
        component_class='RBC',
        abo_type='O',
        rh_d_type='neg',
        status='available',
        owner_branch=branch,
        expiry_datetime=timezone.now() + timedelta(days=42),
    )


@pytest.fixture
def patient(db, user):
    return PatientFactory(created_by=user)


@pytest.fixture
def patient_with_two_abo(db, patient, user):
    """Patient with two concordant O- ABO determinations."""
    PatientBloodGroupFactory(patient=patient, abo='O', rh_d='neg',
                             determined_by=user, is_discrepant=False)
    PatientBloodGroupFactory(patient=patient, abo='O', rh_d='neg',
                             determined_by=user, is_discrepant=False)
    return patient
