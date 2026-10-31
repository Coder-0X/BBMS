"""
REST API viewsets.
All write operations that mutate blood units go through domain modules.
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.utils import timezone

from .serializers import (
    DonorSerializer, DonationSerializer, BloodUnitSerializer,
    UnitStatusEventSerializer, PatientSerializer, PatientAntibodySerializer,
    PatientTransfusionRequirementSerializer, SampleSerializer,
    BloodRequestSerializer, CrossmatchSerializer, IssueTransactionSerializer,
    AlertSerializer, BranchSerializer, ComponentTypeSerializer,
)
from donors.models import Donor, Donation
from inventory.models import BloodUnit, ComponentType, UnitStatusEvent
from patients.models import Patient, PatientAntibody, PatientTransfusionRequirement
from transfusion.models import Sample, BloodRequest, Crossmatch, IssueTransaction, EmergencyRelease
from core.models import Alert, Branch


class BranchViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated]


class ComponentTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ComponentType.objects.all()
    serializer_class = ComponentTypeSerializer
    permission_classes = [IsAuthenticated]


class DonorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Donor.objects.all()
    serializer_class = DonorSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    @action(detail=True, methods=['get'])
    def donations(self, request, pk=None):
        donor = self.get_object()
        qs = donor.donations.order_by('-donated_at')
        return Response(DonationSerializer(qs, many=True).data)

    @action(detail=True, methods=['get'])
    def eligibility(self, request, pk=None):
        donor = self.get_object()
        return Response({'eligible': donor.is_eligible_to_donate(), 'status': donor.deferral_status})


class BloodUnitViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BloodUnit.objects.select_related('component_type', 'owner_branch', 'donation')
    serializer_class = BloodUnitSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch')
        status_val = self.request.query_params.get('status')
        abo = self.request.query_params.get('abo')
        component = self.request.query_params.get('component_class')

        if branch_id:
            qs = qs.filter(owner_branch_id=branch_id)
        if status_val:
            qs = qs.filter(status=status_val)
        if abo:
            qs = qs.filter(abo_type=abo)
        if component:
            qs = qs.filter(component_class=component)
        return qs

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        unit = self.get_object()
        events = unit.status_events.order_by('occurred_at')
        return Response(UnitStatusEventSerializer(events, many=True).data)

    @action(detail=True, methods=['get'])
    def lineage(self, request, pk=None):
        """Vein-to-vein traceability — full ancestor/descendant tree."""
        unit = self.get_object()
        result = _get_unit_lineage(unit)
        return Response(result)

    @action(detail=False, methods=['get'])
    def available(self, request):
        """Quick lookup: available units compatible with given ABO/Rh."""
        abo = request.query_params.get('abo', '')
        rh = request.query_params.get('rh', '')
        component = request.query_params.get('component_class', 'RBC')
        branch = request.query_params.get('branch')

        qs = BloodUnit.objects.filter(status='available', component_class=component)
        if branch:
            qs = qs.filter(owner_branch_id=branch)
        if abo and rh:
            qs = _filter_compatible_units(qs, abo, rh)

        return Response(BloodUnitSerializer(qs[:50], many=True).data)


def _filter_compatible_units(qs, patient_abo, patient_rh):
    """Filter units compatible with the given patient blood type."""
    ABO_COMPATIBLE = {
        'O':  ['O'],
        'A':  ['O', 'A'],
        'B':  ['O', 'B'],
        'AB': ['O', 'A', 'B', 'AB'],
    }
    compatible_abos = ABO_COMPATIBLE.get(patient_abo, [])
    qs = qs.filter(abo_type__in=compatible_abos)
    if patient_rh == 'neg':
        qs = qs.filter(rh_d_type='neg')
    return qs


def _get_unit_lineage(unit):
    """Build ancestor/descendant tree for a unit using recursive lookup."""
    from inventory.models import UnitLineage

    ancestors = []
    current = unit
    while True:
        edge = UnitLineage.objects.filter(child_unit=current).select_related('parent_unit', 'parent_donation').first()
        if not edge:
            break
        ancestors.append({
            'relationship': edge.relationship,
            'parent_unit_did': edge.parent_unit.did if edge.parent_unit else None,
            'parent_donation_id': edge.parent_donation_id,
        })
        if not edge.parent_unit:
            break
        current = edge.parent_unit

    descendants = list(UnitLineage.objects.filter(
        parent_unit=unit
    ).values('child_unit__did', 'relationship'))

    return {
        'did': unit.did,
        'ancestors': ancestors,
        'descendants': descendants,
    }


class PatientViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Patient.objects.filter(record_status='active')
    serializer_class = PatientSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['get'])
    def antibodies(self, request, pk=None):
        patient = self.get_object()
        qs = patient.antibodies.filter(clinical_significance='significant')
        return Response(PatientAntibodySerializer(qs, many=True).data)

    @action(detail=True, methods=['get'])
    def requirements(self, request, pk=None):
        patient = self.get_object()
        qs = patient.special_requirements.filter(active=True)
        return Response(PatientTransfusionRequirementSerializer(qs, many=True).data)

    @action(detail=True, methods=['get'])
    def compatible_units(self, request, pk=None):
        """
        List available units compatible with this patient —
        ABO/Rh + special requirements applied.
        """
        patient = self.get_object()
        component = request.query_params.get('component_class', 'RBC')
        branch = request.query_params.get('branch')

        qs = BloodUnit.objects.filter(status='available', component_class=component)
        if branch:
            qs = qs.filter(owner_branch_id=branch)

        bg = patient.current_blood_group()
        if bg:
            qs = _filter_compatible_units(qs, bg.abo, bg.rh_d)

        # Apply standing special requirements
        for req in patient.active_special_requirements():
            r = req.requirement
            if r == 'irradiated':
                qs = qs.filter(is_irradiated=True)
            elif r == 'cmv_negative':
                qs = qs.filter(is_cmv_negative=True)
            elif r == 'washed':
                qs = qs.filter(is_washed=True)
            elif r == 'leukoreduced_only':
                qs = qs.filter(is_leukoreduced=True)

        return Response(BloodUnitSerializer(qs[:30], many=True).data)


class BloodRequestViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BloodRequest.objects.select_related('patient', 'branch')
    serializer_class = BloodRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        branch = self.request.query_params.get('branch')
        outcome = self.request.query_params.get('outcome')
        urgency = self.request.query_params.get('urgency')
        if branch:
            qs = qs.filter(branch_id=branch)
        if outcome:
            qs = qs.filter(outcome=outcome)
        if urgency:
            qs = qs.filter(urgency=urgency)
        return qs.order_by('-requested_ts')


class SampleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Sample.objects.all()
    serializer_class = SampleSerializer
    permission_classes = [IsAuthenticated]


class IssueTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = IssueTransaction.objects.select_related('blood_unit', 'patient', 'issued_by')
    serializer_class = IssueTransactionSerializer
    permission_classes = [IsAuthenticated]


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Alert.objects.select_related('branch')
    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        branch = self.request.query_params.get('branch')
        unack = self.request.query_params.get('unacknowledged')
        if branch:
            qs = qs.filter(branch_id=branch)
        if unack == '1':
            qs = qs.filter(acknowledged_at__isnull=True)
        return qs.order_by('-created_at')

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        if alert.acknowledged_at:
            return Response({'detail': 'Already acknowledged.'}, status=status.HTTP_400_BAD_REQUEST)
        alert.acknowledged_at = timezone.now()
        alert.acknowledged_by = request.user
        alert.save(update_fields=['acknowledged_at', 'acknowledged_by'])
        return Response({'detail': 'Acknowledged.'})


# ---------------------------------------------------------------------------
# Cold chain — temperature ingest
# ---------------------------------------------------------------------------

from rest_framework.views import APIView as _BaseAPIView


class TemperatureIngestView(_BaseAPIView):
    """
    POST /api/v1/temperature/
    Accept one or a batch of temperature readings from IoT sensors.

    Body (single):
        {"sensor_id": "FRIDGE-01", "temp_c": 4.2, "humidity_pct": 65.0,
         "agitation_ok": null, "recorded_at": "2026-06-17T10:00:00Z"}

    Body (batch):
        [{"sensor_id": ..., ...}, ...]

    Checks temperature against ComponentStorageSpec limits for the equipment
    and auto-creates a TemperatureExcursion + quarantines affected units if
    out-of-range.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from coldchain.models import StorageEquipment, SensorHealth, TemperatureLog, TemperatureExcursion, ExcursionUnitLink
        from inventory.models import BloodUnit
        from django.utils.dateparse import parse_datetime
        import uuid as _uuid

        payload = request.data
        if isinstance(payload, dict):
            payload = [payload]

        created = 0
        errors = []

        for item in payload:
            sensor_id = item.get('sensor_id', '').strip()
            temp_raw  = item.get('temp_c')
            recorded_at_str = item.get('recorded_at')

            if not sensor_id or temp_raw is None:
                errors.append({'sensor_id': sensor_id, 'error': 'sensor_id and temp_c are required'})
                continue

            try:
                equip = StorageEquipment.objects.get(sensor_id=sensor_id, status='active')
            except StorageEquipment.DoesNotExist:
                errors.append({'sensor_id': sensor_id, 'error': 'Unknown or inactive sensor'})
                continue

            recorded_at = parse_datetime(recorded_at_str) if recorded_at_str else timezone.now()
            if recorded_at is None:
                errors.append({'sensor_id': sensor_id, 'error': 'Invalid recorded_at format'})
                continue

            try:
                temp_c = float(temp_raw)
            except (TypeError, ValueError):
                errors.append({'sensor_id': sensor_id, 'error': 'temp_c must be a number'})
                continue
            humidity = item.get('humidity_pct')
            agitation = item.get('agitation_ok')
            reading_uuid = item.get('reading_uuid') or str(_uuid.uuid4())

            # Idempotency — skip duplicate readings
            if TemperatureLog.objects.filter(reading_uuid=reading_uuid).exists():
                continue

            TemperatureLog.objects.create(
                equipment=equip,
                recorded_at=recorded_at,
                temp_c=temp_c,
                humidity_pct=humidity,
                agitation_ok=agitation,
                source='sensor',
                reading_uuid=reading_uuid,
            )
            created += 1

            # Update sensor heartbeat
            SensorHealth.objects.update_or_create(
                sensor_id=sensor_id,
                defaults={'equipment': equip, 'last_seen_at': timezone.now(), 'status': 'ok'},
            )

            # Check against storage spec
            _handle_excursion_check(equip, temp_c, agitation, recorded_at, actor=request.user)

        return Response({'created': created, 'errors': errors},
                        status=status.HTTP_207_MULTI_STATUS if errors else status.HTTP_201_CREATED)


def _handle_excursion_check(equip, temp_c, agitation_ok, recorded_at, actor=None):
    """Open or extend excursion, auto-quarantine units in the equipment."""
    from coldchain.models import TemperatureExcursion, ExcursionUnitLink
    from inventory.models import BloodUnit
    from coldchain.models import ComponentStorageSpec
    from inventory.state_machine import transition_unit
    from audit.utils import write_audit

    spec = ComponentStorageSpec.objects.filter(
        component_class=equip.component_class_allowed
    ).first() if equip.component_class_allowed else None

    in_range = True
    if spec:
        if temp_c < float(spec.storage_temp_min_c) or temp_c > float(spec.storage_temp_max_c):
            in_range = False
        if spec.requires_agitation and agitation_ok is False:
            in_range = False

    ongoing = TemperatureExcursion.objects.filter(equipment=equip, ended_at__isnull=True).first()

    if not in_range:
        if ongoing is None:
            exc = TemperatureExcursion.objects.create(
                equipment=equip,
                started_at=recorded_at,
                max_temp_c=temp_c,
                min_temp_c=temp_c,
                auto_quarantine=True,
            )
            if actor:
                write_audit(
                    actor=actor,
                    action='coldchain.excursion.opened',
                    entity_table='coldchain_temperatureexcursion',
                    entity_id=exc.pk,
                    after={'equipment_id': equip.pk, 'temp_c': temp_c},
                    branch=equip.branch,
                )
            # Auto-quarantine all available units in this equipment
            units = BloodUnit.objects.filter(
                storage_equipment=equip,
                status='available',
            )
            for u in units:
                ExcursionUnitLink.objects.get_or_create(excursion=exc, blood_unit=u)
                if actor:
                    try:
                        transition_unit(
                            u, 'quarantined_holdback', actor,
                            reason=f"Auto-quarantine: temperature excursion #{exc.pk} on {equip.name}",
                        )
                    except Exception:
                        pass
        else:
            # Extend the excursion — update min/max
            update_fields = []
            if ongoing.max_temp_c is None or temp_c > float(ongoing.max_temp_c):
                ongoing.max_temp_c = temp_c
                update_fields.append('max_temp_c')
            if ongoing.min_temp_c is None or temp_c < float(ongoing.min_temp_c):
                ongoing.min_temp_c = temp_c
                update_fields.append('min_temp_c')
            if update_fields:
                ongoing.save(update_fields=update_fields)
    else:
        # Temperature back in range — close the excursion
        if ongoing:
            ongoing.ended_at = recorded_at
            ongoing.save(update_fields=['ended_at'])


# ---------------------------------------------------------------------------
# Health check — no authentication required
# ---------------------------------------------------------------------------

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny


class HealthView(APIView):
    """
    GET /api/v1/health/
    Returns 200 when the application + database are reachable.
    Returns 503 when the DB check fails.
    No authentication required (used by load balancers / uptime monitors).
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        from django.db import connection
        checks = {}
        overall = 'ok'
        try:
            with connection.cursor() as cur:
                cur.execute('SELECT 1')
            checks['database'] = 'ok'
        except Exception as exc:
            checks['database'] = f'error: {exc}'
            overall = 'degraded'

        http_status = 200 if overall == 'ok' else 503
        return Response({'status': overall, 'checks': checks}, status=http_status)


# ---------------------------------------------------------------------------
# Token management — get or create your own API token
# ---------------------------------------------------------------------------

class TokenView(APIView):
    """
    GET  /api/v1/auth/token/  — retrieve your current token (creates one if absent)
    DELETE /api/v1/auth/token/ — revoke your token
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from rest_framework.authtoken.models import Token
        token, _ = Token.objects.get_or_create(user=request.user)
        return Response({'token': token.key})

    def delete(self, request):
        from rest_framework.authtoken.models import Token
        Token.objects.filter(user=request.user).delete()
        return Response({'detail': 'Token revoked.'}, status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Bedside PWA — pre-transfusion patient/unit verification
# ---------------------------------------------------------------------------

class BedsideVerifyView(_BaseAPIView):
    """
    POST /api/v1/bedside/verify/
    Verify that a scanned wristband (patient_uid) matches a scanned blood
    unit (unit_did) via the IssueTransaction linking them.

    Returns a deterministic pass/fail with ABO compatibility check embedded.
    Never returns cached data — always hits DB (network-first in Service Worker).

    Body:
        {"patient_uid": "<mpi_uid>", "unit_did": "<BloodUnit.did>"}
    """
    permission_classes = [IsAuthenticated]

    _ABO_RBC_COMPAT = {
        'O':  ['O'],
        'A':  ['O', 'A'],
        'B':  ['O', 'B'],
        'AB': ['O', 'A', 'B', 'AB'],
    }

    def post(self, request):
        from patients.models import Patient
        from inventory.models import BloodUnit
        from transfusion.models import IssueTransaction
        from privacy.vault import decrypt
        from audit.utils import write_audit

        patient_uid = (request.data.get('patient_uid') or '').strip()
        unit_did    = (request.data.get('unit_did') or '').strip()

        if not patient_uid or not unit_did:
            return Response(
                {'status': 'error', 'reason': 'MISSING_PARAMS',
                 'detail': 'Both patient_uid and unit_did are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Look up patient
        try:
            patient = Patient.objects.select_related('subject').get(mpi_uid=patient_uid)
        except (Patient.DoesNotExist, Exception):
            return Response(
                {'status': 'fail', 'reason': 'PATIENT_NOT_FOUND',
                 'detail': 'No patient record found for the scanned wristband.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Look up blood unit
        try:
            unit = BloodUnit.objects.select_related('component_type').get(did=unit_did)
        except BloodUnit.DoesNotExist:
            return Response(
                {'status': 'fail', 'reason': 'UNIT_NOT_FOUND',
                 'detail': 'No blood unit found for the scanned DID.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Find an IssueTransaction linking this patient to this unit
        tx = (
            IssueTransaction.objects
            .filter(patient=patient, blood_unit=unit)
            .order_by('-issued_at')
            .first()
        )

        checks = {
            'patient_unit_linked': tx is not None,
            'unit_status_issued': unit.status == 'issued',
            'abo_compatible': False,
        }

        if tx is None:
            write_audit(
                actor=request.user,
                action='bedside.verify.fail.no_link',
                entity_table='transfusion_issuetransaction',
                entity_id=0,
                after={'patient_uid': patient_uid, 'unit_did': unit_did, 'reason': 'PATIENT_UNIT_MISMATCH'},
            )
            return Response(
                {'status': 'fail', 'reason': 'PATIENT_UNIT_MISMATCH',
                 'detail': 'This blood unit is not issued for this patient.'},
                status=status.HTTP_200_OK,
            )

        # ABO compatibility: patient group vs unit group.
        # Fail-safe: if the patient's ABO is unknown (no lab-confirmed and no
        # declared group), the fallback must be an EMPTY list so the check fails
        # rather than passing. A `[unit_abo]` fallback would make the test always
        # pass for an unknown-group patient — a fail-OPEN bug at the bedside, the
        # last barrier against wrong-blood transfusion.
        patient_bg = patient.effective_blood_group()
        patient_abo = patient_bg.abo if patient_bg else patient.abo
        unit_abo    = unit.abo_type
        checks['abo_compatible'] = bool(patient_abo) and unit_abo in self._ABO_RBC_COMPAT.get(patient_abo, [])

        overall = all(checks.values())

        # Decrypt patient name for display (safe for clinical staff)
        patient_name = decrypt(patient.subject.name_enc) if patient.subject.name_enc else f'Patient #{patient.pk}'

        write_audit(
            actor=request.user,
            action='bedside.verify.pass' if overall else 'bedside.verify.fail',
            entity_table='transfusion_issuetransaction',
            entity_id=tx.pk,
            after={
                'unit_did': unit_did,
                'patient_uid': patient_uid,
                'checks': checks,
            },
        )

        return Response({
            'status': 'pass' if overall else 'fail',
            'reason': None if overall else 'CHECK_FAILED',
            'patient_name': patient_name,
            'patient_abo': patient_abo,
            'patient_rh_d': patient_bg.rh_d if patient_bg else patient.rh_d,
            'unit_did': unit.did,
            'unit_abo': unit.abo_type,
            'unit_rh_d': unit.rh_d_type,
            'component_name': unit.component_type.name,
            'expiry': unit.expiry_datetime,
            'issue_tx_id': tx.pk,
            'checks': checks,
        }, status=status.HTTP_200_OK)
