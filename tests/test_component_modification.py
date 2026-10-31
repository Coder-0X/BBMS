"""
Component modification guided workflow tests.

Covers:
  - Leukoreduction: records ProcessingEvent, sets is_leukoreduced, e-signs, guards
  - Wash: records ProcessingEvent, sets is_washed, e-signs, guards
  - Platelet pooling: creates pooled unit, records lineage, marks inputs consumed
"""
import pytest
from datetime import timedelta
from django.utils import timezone
from django.test import Client

from tests.conftest import (
    UserFactory, BranchFactory, DonorFactory, DonationFactory, BloodUnitFactory,
)


def _make_plt_unit(branch, user, leukoreduced=False, irradiated=False):
    donor = DonorFactory(registration_branch=branch, created_by=user)
    donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
    return BloodUnitFactory(
        donation=donation, owner_branch=branch,
        status='available', component_class='PLT',
        is_leukoreduced=leukoreduced, is_irradiated=irradiated,
        expiry_datetime=timezone.now() + timedelta(days=5),
        volume_ml=55,
    )


def _make_rbc_unit(branch, user):
    donor = DonorFactory(registration_branch=branch, created_by=user)
    donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
    return BloodUnitFactory(
        donation=donation, owner_branch=branch,
        status='available', component_class='RBC',
    )


# ─── Leukoreduction ───────────────────────────────────────────────────────────

class TestLeukoreductionUnit:

    def test_leukoreduction_sets_flag_and_creates_event(self, db, branch, user):
        from inventory.models import ProcessingEvent
        unit = _make_rbc_unit(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post(f'/inventory/units/{unit.did}/leukoreduction/', {
            'filter_lot': 'PALL-RC2D-001',
            'sop_version': 'LR-SOP-01',
            'pre_leukocyte_count': '2.1',
            'post_leukocyte_count': '0.05',
        })
        assert response.status_code == 302
        unit.refresh_from_db()
        assert unit.is_leukoreduced is True
        event = ProcessingEvent.objects.filter(blood_unit=unit, event_type='leukoreduction').first()
        assert event is not None
        assert 'PALL-RC2D-001' in event.notes
        assert event.esign is not None

    def test_leukoreduction_missing_filter_lot_shows_error(self, db, branch, user):
        unit = _make_rbc_unit(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post(f'/inventory/units/{unit.did}/leukoreduction/', {
            'filter_lot': '',
            'sop_version': 'LR-SOP-01',
        })
        assert response.status_code == 200  # re-renders with error
        unit.refresh_from_db()
        assert unit.is_leukoreduced is False

    def test_already_leukoreduced_redirects(self, db, branch, user):
        unit = _make_rbc_unit(branch, user)
        unit.is_leukoreduced = True
        unit.save(update_fields=['is_leukoreduced'])
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.get(f'/inventory/units/{unit.did}/leukoreduction/')
        assert response.status_code == 302

    def test_issued_unit_cannot_be_leukoreduced(self, db, branch, user):
        unit = _make_rbc_unit(branch, user)
        unit.status = 'issued'
        unit.save(update_fields=['status'])
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.get(f'/inventory/units/{unit.did}/leukoreduction/')
        assert response.status_code == 302  # redirected with error


# ─── Wash ─────────────────────────────────────────────────────────────────────

class TestWashUnit:

    def test_wash_sets_flag_and_creates_event(self, db, branch, user):
        from inventory.models import ProcessingEvent
        unit = _make_rbc_unit(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post(f'/inventory/units/{unit.did}/wash/', {
            'indication': 'iga_deficiency',
            'wash_solution': 'normal_saline',
            'num_washes': '3',
            'wash_vol_ml': '150',
            'sop_version': 'WASH-SOP-01',
        })
        assert response.status_code == 302
        unit.refresh_from_db()
        assert unit.is_washed is True
        event = ProcessingEvent.objects.filter(blood_unit=unit, event_type='wash').first()
        assert event is not None
        assert 'iga_deficiency' in event.notes
        assert event.esign is not None

    def test_wash_missing_indication_shows_error(self, db, branch, user):
        unit = _make_rbc_unit(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post(f'/inventory/units/{unit.did}/wash/', {
            'indication': '',
            'sop_version': 'WASH-SOP-01',
        })
        assert response.status_code == 200
        unit.refresh_from_db()
        assert unit.is_washed is False

    def test_wash_template_renders(self, db, branch, user):
        unit = _make_rbc_unit(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.get(f'/inventory/units/{unit.did}/wash/')
        assert response.status_code == 200
        assert b'Wash' in response.content


# ─── Platelet Pooling ─────────────────────────────────────────────────────────

class TestPoolPlatelets:

    def _setup_plt_units(self, branch, user, count=5):
        from inventory.models import ComponentType
        ComponentType.objects.get_or_create(
            code='PLT_STD',
            defaults={
                'name': 'Platelets Standard',
                'component_class': 'PLT',
                'shelf_life_hours': 168,
                'storage_temp_min_c': 20.0,
                'storage_temp_max_c': 24.0,
            }
        )
        from core.models import RefFacility
        RefFacility.objects.get_or_create(branch=branch, defaults={'facility_code': 'TST'})
        return [_make_plt_unit(branch, user) for _ in range(count)]

    def test_pool_creates_new_unit_and_lineage(self, db, branch, user):
        from inventory.models import BloodUnit, UnitLineage
        units = self._setup_plt_units(branch, user, count=4)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post('/inventory/units/pool-platelets/', {
            'unit_pks': [str(u.pk) for u in units],
            'sop_version': 'PLT-POOL-SOP-01',
            'notes': 'Test pool',
        })
        assert response.status_code == 302
        # Verify lineage
        new_unit_pk = max(BloodUnit.objects.filter(component_class='PLT').values_list('pk', flat=True))
        lineage_edges = UnitLineage.objects.filter(child_unit_id=new_unit_pk)
        assert lineage_edges.count() == 4
        # Verify inputs are consumed
        for u in units:
            u.refresh_from_db()
            assert u.status == 'issued'

    def test_pool_under_minimum_shows_error(self, db, branch, user):
        units = self._setup_plt_units(branch, user, count=3)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post('/inventory/units/pool-platelets/', {
            'unit_pks': [str(u.pk) for u in units],
            'sop_version': 'PLT-POOL-SOP-01',
        })
        assert response.status_code == 200  # re-renders with error

    def test_pool_over_maximum_shows_error(self, db, branch, user):
        units = self._setup_plt_units(branch, user, count=7)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post('/inventory/units/pool-platelets/', {
            'unit_pks': [str(u.pk) for u in units],
            'sop_version': 'PLT-POOL-SOP-01',
        })
        assert response.status_code == 200

    def test_pool_expiry_is_earliest_input(self, db, branch, user):
        from inventory.models import BloodUnit
        units = self._setup_plt_units(branch, user, count=4)
        # Set different expiries
        for i, u in enumerate(units):
            u.expiry_datetime = timezone.now() + timedelta(days=i + 1)
            u.save(update_fields=['expiry_datetime'])
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        c.post('/inventory/units/pool-platelets/', {
            'unit_pks': [str(u.pk) for u in units],
            'sop_version': 'PLT-POOL-SOP-01',
        })
        # Pool unit is the last created PLT
        pool = BloodUnit.objects.filter(component_class='PLT').order_by('-pk').first()
        earliest_expiry = min(u.expiry_datetime for u in units)
        assert abs((pool.expiry_datetime - earliest_expiry).total_seconds()) < 5

    def test_pool_page_renders_available_units(self, db, branch, user):
        self._setup_plt_units(branch, user, count=4)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.get('/inventory/units/pool-platelets/')
        assert response.status_code == 200

    def test_pool_inherits_leukoreduced_if_all_leukoreduced(self, db, branch, user):
        from inventory.models import BloodUnit
        units = []
        for _ in range(4):
            u = _make_plt_unit(branch, user, leukoreduced=True)
            units.append(u)
        from core.models import RefFacility
        RefFacility.objects.get_or_create(branch=branch, defaults={'facility_code': 'TST'})
        from inventory.models import ComponentType
        ComponentType.objects.get_or_create(
            code='PLT_STD',
            defaults={'name': 'Platelets Standard', 'component_class': 'PLT',
                      'shelf_life_hours': 168, 'storage_temp_min_c': 20.0, 'storage_temp_max_c': 24.0}
        )
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        c.post('/inventory/units/pool-platelets/', {
            'unit_pks': [str(u.pk) for u in units],
            'sop_version': 'PLT-POOL-SOP-01',
        })
        pool = BloodUnit.objects.filter(component_class='PLT').order_by('-pk').first()
        assert pool.is_leukoreduced is True
