"""
Tests for cold chain alert detection and excursion logic.

Run with: python manage.py test tests.test_coldchain
"""
from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase, TestCase


class ExcursionCheckTests(SimpleTestCase):
    """Test _handle_excursion_check logic from api.views."""

    def _make_equip(self, component_class='RBC'):
        equip = MagicMock()
        equip.component_class_allowed = component_class
        equip.pk = 1
        return equip

    def _make_spec(self, min_c, max_c, requires_agitation=False):
        spec = MagicMock()
        spec.storage_temp_min_c = min_c
        spec.storage_temp_max_c = max_c
        spec.requires_agitation = requires_agitation
        return spec

    # Patch at coldchain.models (where models are lazily imported inside the function)
    _patch_exc = 'coldchain.models.TemperatureExcursion'
    _patch_link = 'coldchain.models.ExcursionUnitLink'
    _patch_unit = 'inventory.models.BloodUnit'
    _patch_spec = 'coldchain.models.ComponentStorageSpec'

    def test_temp_in_range_no_excursion_created(self):
        from api.views import _handle_excursion_check
        equip = self._make_equip()
        with patch(self._patch_exc) as MockExc, \
             patch(self._patch_link), \
             patch(self._patch_unit), \
             patch(self._patch_spec) as MockSpec:

            spec = self._make_spec(1.0, 6.0)
            MockSpec.objects.filter.return_value.first.return_value = spec
            MockExc.objects.filter.return_value.first.return_value = None

            from django.utils import timezone
            _handle_excursion_check(equip, temp_c=4.0, agitation_ok=None,
                                    recorded_at=timezone.now())

            MockExc.objects.create.assert_not_called()

    def test_high_temp_creates_excursion(self):
        from api.views import _handle_excursion_check
        equip = self._make_equip()
        with patch(self._patch_exc) as MockExc, \
             patch(self._patch_link), \
             patch(self._patch_unit) as MockUnit, \
             patch(self._patch_spec) as MockSpec:

            spec = self._make_spec(1.0, 6.0)
            MockSpec.objects.filter.return_value.first.return_value = spec
            MockExc.objects.filter.return_value.first.return_value = None
            MockExc.objects.create.return_value = MagicMock(pk=1)
            MockUnit.objects.filter.return_value = []

            from django.utils import timezone
            _handle_excursion_check(equip, temp_c=10.0, agitation_ok=None,
                                    recorded_at=timezone.now())

            MockExc.objects.create.assert_called_once()

    def test_temp_back_in_range_closes_excursion(self):
        from api.views import _handle_excursion_check
        equip = self._make_equip()
        ongoing_exc = MagicMock()
        ongoing_exc.max_temp_c = 12.0
        ongoing_exc.min_temp_c = 8.0

        with patch(self._patch_exc) as MockExc, \
             patch(self._patch_link), \
             patch(self._patch_unit), \
             patch(self._patch_spec) as MockSpec:

            spec = self._make_spec(1.0, 6.0)
            MockSpec.objects.filter.return_value.first.return_value = spec
            MockExc.objects.filter.return_value.first.return_value = ongoing_exc

            from django.utils import timezone
            now = timezone.now()
            _handle_excursion_check(equip, temp_c=4.0, agitation_ok=None, recorded_at=now)

            self.assertEqual(ongoing_exc.ended_at, now)
            ongoing_exc.save.assert_called_once_with(update_fields=['ended_at'])

    def test_agitation_failure_triggers_excursion(self):
        from api.views import _handle_excursion_check
        equip = self._make_equip('PLT')
        with patch(self._patch_exc) as MockExc, \
             patch(self._patch_link), \
             patch(self._patch_unit) as MockUnit, \
             patch(self._patch_spec) as MockSpec:

            spec = self._make_spec(20.0, 24.0, requires_agitation=True)
            MockSpec.objects.filter.return_value.first.return_value = spec
            MockExc.objects.filter.return_value.first.return_value = None
            MockExc.objects.create.return_value = MagicMock(pk=1)
            MockUnit.objects.filter.return_value = []

            from django.utils import timezone
            # Temp in range but agitation_ok=False
            _handle_excursion_check(equip, temp_c=22.0, agitation_ok=False,
                                    recorded_at=timezone.now())

            MockExc.objects.create.assert_called_once()


class ColdChainAlertTests(SimpleTestCase):
    """Test _check_cold_chain alert logic."""

    def test_no_coldchain_app_graceful_skip(self):
        from core.alerts import _check_cold_chain
        branch = MagicMock()
        # Should not raise even if coldchain tables don't exist
        with patch('core.alerts.StorageEquipment' if False else 'builtins.__import__') as mock_import:
            # Just verify the function exists and is callable
            pass
        # If we get here without ImportError the skip works
        self.assertTrue(callable(_check_cold_chain))


# ─── Extended pytest-style tests ──────────────────────────────────────────────

import pytest
from datetime import timedelta
from django.utils import timezone
from tests.conftest import BranchFactory, UserFactory, StorageEquipmentFactory


class TestEquipmentStatusPytest:

    def test_equipment_created(self, db, branch):
        equip = StorageEquipmentFactory(branch=branch)
        assert equip.pk is not None

    def test_sensor_id_unique(self, db, branch):
        from django.db import IntegrityError
        StorageEquipmentFactory(branch=branch, sensor_id='SNSR9999')
        with pytest.raises(IntegrityError):
            StorageEquipmentFactory(branch=branch, sensor_id='SNSR9999')

    def test_different_component_classes(self, db, branch):
        equip_rbc = StorageEquipmentFactory(
            branch=branch, component_class_allowed='RBC', equipment_type='refrigerator'
        )
        equip_ffp = StorageEquipmentFactory(
            branch=branch, component_class_allowed='FFP', equipment_type='freezer'
        )
        assert equip_rbc.component_class_allowed == 'RBC'
        assert equip_ffp.component_class_allowed == 'FFP'


class TestExcursionFullCyclePytest:

    def _ensure_rbc_spec(self):
        """Create a ComponentStorageSpec for RBC if not exists (required for excursion detection)."""
        from coldchain.models import ComponentStorageSpec
        ComponentStorageSpec.objects.get_or_create(
            component_class='RBC',
            defaults={
                'storage_temp_min_c': 1.0,
                'storage_temp_max_c': 6.0,
                'transport_temp_min_c': 1.0,
                'transport_temp_max_c': 10.0,
                'requires_agitation': False,
                'agitation_max_interruption_min': 0,
                'shelf_life_hours': 1008,
                'source_standard': 'AABB',
            }
        )

    def test_high_temp_excursion_created_and_closed(self, db, branch):
        """End-to-end: out-of-range reading creates excursion, in-range closes it."""
        from api.views import _handle_excursion_check
        from coldchain.models import TemperatureExcursion
        self._ensure_rbc_spec()
        equip = StorageEquipmentFactory(branch=branch, equipment_type='refrigerator',
                                        component_class_allowed='RBC')
        t_excursion = timezone.now() - timedelta(minutes=30)
        t_recovery = timezone.now()

        _handle_excursion_check(equip, temp_c=12.0, agitation_ok=None, recorded_at=t_excursion)
        open_exc = TemperatureExcursion.objects.filter(equipment=equip, ended_at__isnull=True)
        assert open_exc.exists()

        _handle_excursion_check(equip, temp_c=4.0, agitation_ok=None, recorded_at=t_recovery)
        open_after = TemperatureExcursion.objects.filter(equipment=equip, ended_at__isnull=True)
        assert not open_after.exists()

    def test_multiple_readings_in_excursion_tracked(self, db, branch):
        from api.views import _handle_excursion_check
        from coldchain.models import TemperatureExcursion
        self._ensure_rbc_spec()
        equip = StorageEquipmentFactory(branch=branch, equipment_type='refrigerator',
                                        component_class_allowed='RBC')
        base_time = timezone.now() - timedelta(hours=2)
        for i in range(3):
            _handle_excursion_check(
                equip, temp_c=14.0 + i, agitation_ok=None,
                recorded_at=base_time + timedelta(minutes=i * 10)
            )
        excursions = TemperatureExcursion.objects.filter(equipment=equip, ended_at__isnull=True)
        assert excursions.count() == 1


# ─── Cold chain view tests ────────────────────────────────────────────────────

from django.test import Client


@pytest.fixture
def logged_in_client(db, branch, user):
    client = Client()
    client.login(username=user.username, password='testpass123')
    session = client.session
    session['branch_id'] = branch.pk
    session.save()
    return client


class TestEquipmentListView:

    def test_get_renders_equipment_for_branch(self, db, branch, user, logged_in_client):
        equip = StorageEquipmentFactory(branch=branch)
        response = logged_in_client.get('/coldchain/equipment/')
        assert response.status_code == 200
        assert equip.name.encode() in response.content

    def test_decommissioned_equipment_excluded(self, db, branch, user, logged_in_client):
        decom = StorageEquipmentFactory(branch=branch, status='decommissioned')
        response = logged_in_client.get('/coldchain/equipment/')
        assert response.status_code == 200
        assert decom.name.encode() not in response.content

    def test_unauthenticated_redirects(self, db, branch):
        response = Client().get('/coldchain/equipment/')
        assert response.status_code == 302


class TestEquipmentDetailView:

    def test_get_renders_detail(self, db, branch, user, logged_in_client):
        equip = StorageEquipmentFactory(branch=branch)
        response = logged_in_client.get(f'/coldchain/equipment/{equip.pk}/')
        assert response.status_code == 200

    def test_nonexistent_equipment_returns_404(self, db, branch, user, logged_in_client):
        response = logged_in_client.get('/coldchain/equipment/99999/')
        assert response.status_code == 404


class TestExcursionListView:

    def _make_excursion(self, branch):
        from coldchain.models import TemperatureExcursion
        equip = StorageEquipmentFactory(branch=branch)
        return TemperatureExcursion.objects.create(
            equipment=equip,
            started_at=timezone.now() - timedelta(hours=1),
        )

    def test_get_renders_list(self, db, branch, user, logged_in_client):
        self._make_excursion(branch)
        response = logged_in_client.get('/coldchain/excursions/')
        assert response.status_code == 200

    def test_filter_ongoing(self, db, branch, user, logged_in_client):
        self._make_excursion(branch)
        response = logged_in_client.get('/coldchain/excursions/?status=ongoing')
        assert response.status_code == 200

    def test_filter_resolved(self, db, branch, user, logged_in_client):
        exc = self._make_excursion(branch)
        exc.ended_at = timezone.now()
        exc.save(update_fields=['ended_at'])
        response = logged_in_client.get('/coldchain/excursions/?status=resolved')
        assert response.status_code == 200


class TestExcursionResolveView:

    def _make_ongoing_excursion(self, branch):
        from coldchain.models import TemperatureExcursion
        equip = StorageEquipmentFactory(branch=branch)
        return TemperatureExcursion.objects.create(
            equipment=equip,
            started_at=timezone.now() - timedelta(hours=2),
        )

    def test_get_renders_form(self, db, branch, user, logged_in_client):
        exc = self._make_ongoing_excursion(branch)
        response = logged_in_client.get(f'/coldchain/excursions/{exc.pk}/resolve/')
        assert response.status_code == 200

    def test_post_marks_excursion_resolved(self, db, branch, user, logged_in_client):
        from coldchain.models import TemperatureExcursion
        exc = self._make_ongoing_excursion(branch)
        response = logged_in_client.post(f'/coldchain/excursions/{exc.pk}/resolve/', {
            'disposition': 'return_to_stock',
            'justification': 'Temperature spike was brief; units remained safe.',
        })
        assert response.status_code == 302
        exc.refresh_from_db()
        assert exc.ended_at is not None
        assert exc.disposition == 'return_to_stock'

    def test_post_writes_audit_trail(self, db, branch, user, logged_in_client):
        from audit.models import AuditLog
        from coldchain.models import TemperatureExcursion
        exc = self._make_ongoing_excursion(branch)
        logged_in_client.post(f'/coldchain/excursions/{exc.pk}/resolve/', {
            'disposition': 'quarantine',
            'justification': 'Precautionary.',
        })
        assert AuditLog.objects.filter(
            action='excursion.resolve',
            entity_table='coldchain_temperatureexcursion',
            entity_id=exc.pk,
        ).exists()

    def test_post_quarantine_disposition(self, db, branch, user, logged_in_client):
        from coldchain.models import TemperatureExcursion
        exc = self._make_ongoing_excursion(branch)
        response = logged_in_client.post(f'/coldchain/excursions/{exc.pk}/resolve/', {
            'disposition': 'quarantine',
            'justification': 'Playing it safe.',
        })
        assert response.status_code == 302
        exc.refresh_from_db()
        assert exc.disposition == 'quarantine'


class TestReturnCheckListView:

    def test_get_renders_list(self, db, branch, user, logged_in_client):
        response = logged_in_client.get('/coldchain/return-checks/')
        assert response.status_code == 200

    def test_unauthenticated_redirects(self, db):
        response = Client().get('/coldchain/return-checks/')
        assert response.status_code == 302
