"""
Surgical blood order tests.

Covers:
  - SurgicalBloodOrder model: MSBOS auto-lookup on create, no-match path
  - Create view: creates order, mirrors MSBOS suggestion
  - Approve view: creates BloodRequest, sets status=approved
  - Cancel view: sets status=cancelled, cancels linked request
  - List and detail views render correctly
"""
import pytest
from django.utils import timezone
from datetime import timedelta
from django.test import Client

from tests.conftest import UserFactory, BranchFactory, PatientFactory


def _make_msbos(branch, procedure_code='CABG', order_type='crossmatch', units=2):
    from transfusion.models import MSBOS
    obj, _ = MSBOS.objects.get_or_create(
        procedure_code=procedure_code, branch=branch,
        defaults={'order_type': order_type, 'units_count': units},
    )
    return obj


def _make_order(branch, user, patient=None, procedure_code='CABG', days_ahead=3):
    from transfusion.models import SurgicalBloodOrder
    if patient is None:
        patient = PatientFactory(created_by=user)
    return SurgicalBloodOrder.objects.create(
        patient=patient,
        branch=branch,
        procedure_code=procedure_code,
        procedure_name='Coronary Artery Bypass Graft',
        scheduled_datetime=timezone.now() + timedelta(days=days_ahead),
        component_class='RBC',
        surgeon=user,
        created_by=user,
    )


# ─── Model: MSBOS lookup ─────────────────────────────────────────────────────

class TestSurgicalBloodOrderModel:

    def test_msbos_lookup_on_create(self, db, branch, user):
        _make_msbos(branch, 'THR', 'crossmatch', 3)
        from transfusion.models import SurgicalBloodOrder
        order = SurgicalBloodOrder.objects.create(
            patient=PatientFactory(created_by=user),
            branch=branch,
            procedure_code='THR',
            scheduled_datetime=timezone.now() + timedelta(days=5),
            component_class='RBC',
            surgeon=user, created_by=user,
        )
        assert order.msbos_matched is True
        assert order.msbos_order_type == 'crossmatch'
        assert order.msbos_units_suggested == 3

    def test_no_msbos_entry_sets_matched_false(self, db, branch, user):
        from transfusion.models import SurgicalBloodOrder
        order = SurgicalBloodOrder.objects.create(
            patient=PatientFactory(created_by=user),
            branch=branch,
            procedure_code='UNKNOWN_PROC',
            scheduled_datetime=timezone.now() + timedelta(days=1),
            component_class='RBC',
            surgeon=user, created_by=user,
        )
        assert order.msbos_matched is False
        assert order.msbos_units_suggested == 0

    def test_global_msbos_used_when_no_branch_specific(self, db, branch, user):
        """Branch-null MSBOS entry should be picked up when no branch-specific one exists."""
        from transfusion.models import MSBOS, SurgicalBloodOrder
        MSBOS.objects.get_or_create(
            procedure_code='LSCS', branch=None,
            defaults={'order_type': 'type_and_screen', 'units_count': 0},
        )
        order = SurgicalBloodOrder.objects.create(
            patient=PatientFactory(created_by=user),
            branch=branch,
            procedure_code='LSCS',
            scheduled_datetime=timezone.now() + timedelta(days=2),
            component_class='RBC',
            surgeon=user, created_by=user,
        )
        assert order.msbos_matched is True
        assert order.msbos_order_type == 'type_and_screen'

    def test_str_repr(self, db, branch, user):
        order = _make_order(branch, user, procedure_code='CABG')
        assert 'CABG' in str(order)
        assert 'Patient' in str(order)


# ─── Create view ─────────────────────────────────────────────────────────────

class TestSurgicalOrderCreateView:

    def test_create_order_via_post(self, db, branch, user):
        from transfusion.models import SurgicalBloodOrder
        patient = PatientFactory(created_by=user)
        _make_msbos(branch, 'CABG', 'crossmatch', 2)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        sched = (timezone.now() + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M')
        response = c.post(f'/transfusion/surgical-orders/patient/{patient.pk}/new/', {
            'procedure_code': 'CABG',
            'procedure_name': 'Coronary Artery Bypass',
            'scheduled_datetime': sched,
            'component_class': 'RBC',
            'notes': 'Elective CABG ×3',
        })
        assert response.status_code == 302
        order = SurgicalBloodOrder.objects.filter(patient=patient).first()
        assert order is not None
        assert order.msbos_matched is True
        assert order.procedure_code == 'CABG'

    def test_missing_required_fields_shows_error(self, db, branch, user):
        patient = PatientFactory(created_by=user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post(f'/transfusion/surgical-orders/patient/{patient.pk}/new/', {
            'procedure_code': '',  # missing
            'scheduled_datetime': '',  # missing
        })
        assert response.status_code == 200  # re-renders with error


# ─── Approve view ─────────────────────────────────────────────────────────────

class TestSurgicalOrderApproveView:

    def test_approve_creates_blood_request(self, db, branch, user):
        from transfusion.models import SurgicalBloodOrder, BloodRequest
        order = _make_order(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post(f'/transfusion/surgical-orders/{order.pk}/approve/', {
            'approved_order_type': 'crossmatch',
            'approved_units': '2',
        })
        assert response.status_code == 302
        order.refresh_from_db()
        assert order.status == 'approved'
        assert order.approved_by == user
        assert order.blood_request is not None
        assert order.blood_request.units_requested == 2

    def test_approve_with_type_and_screen_no_blood_request(self, db, branch, user):
        """Type & screen with 0 units should not create a BloodRequest."""
        from transfusion.models import SurgicalBloodOrder, BloodRequest
        order = _make_order(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        c.post(f'/transfusion/surgical-orders/{order.pk}/approve/', {
            'approved_order_type': 'type_and_screen',
            'approved_units': '0',
        })
        order.refresh_from_db()
        assert order.status == 'approved'
        assert order.blood_request is None

    def test_approve_already_approved_redirects(self, db, branch, user):
        order = _make_order(branch, user)
        order.status = 'approved'
        order.save(update_fields=['status'])
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post(f'/transfusion/surgical-orders/{order.pk}/approve/', {
            'approved_order_type': 'crossmatch', 'approved_units': '2',
        })
        assert response.status_code == 302  # redirected with warning


# ─── Cancel view ─────────────────────────────────────────────────────────────

class TestSurgicalOrderCancelView:

    def test_cancel_sets_status(self, db, branch, user):
        order = _make_order(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.post(f'/transfusion/surgical-orders/{order.pk}/cancel/')
        assert response.status_code == 302
        order.refresh_from_db()
        assert order.status == 'cancelled'

    def test_cancel_also_cancels_linked_blood_request(self, db, branch, user):
        from transfusion.models import BloodRequest
        order = _make_order(branch, user)
        patient = order.patient
        # simulate prior approval that created a blood request
        br = BloodRequest.objects.create(
            patient=patient, branch=branch,
            component_class='RBC', units_requested=2,
            urgency='routine', requesting_physician=user,
        )
        order.blood_request = br
        order.status = 'approved'
        order.save(update_fields=['blood_request', 'status'])

        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        c.post(f'/transfusion/surgical-orders/{order.pk}/cancel/')
        br.refresh_from_db()
        assert br.outcome == 'cancelled'


# ─── List and detail views ────────────────────────────────────────────────────

class TestSurgicalOrderViews:

    def test_list_view_renders(self, db, branch, user):
        _make_order(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.get('/transfusion/surgical-orders/')
        assert response.status_code == 200

    def test_detail_view_renders(self, db, branch, user):
        order = _make_order(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.get(f'/transfusion/surgical-orders/{order.pk}/')
        assert response.status_code == 200
        assert b'CABG' in response.content

    def test_approve_page_renders(self, db, branch, user):
        order = _make_order(branch, user)
        c = Client()
        c.login(username=user.username, password='testpass123')
        session = c.session
        session['branch_id'] = branch.pk
        session.save()
        response = c.get(f'/transfusion/surgical-orders/{order.pk}/approve/')
        assert response.status_code == 200
