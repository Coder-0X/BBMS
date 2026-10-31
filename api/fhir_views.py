"""
FHIR R4 read-only facade.

Endpoints:
  GET /fhir/metadata                          — CapabilityStatement
  GET /fhir/Patient/{id}                      — Patient resource
  GET /fhir/BiologicallyDerivedProduct/{did}  — Blood unit resource
  GET /fhir/AuditEvent                        — Recent audit events (?patient=, ?date=)

All responses use Content-Type: application/fhir+json.
No SMART-on-FHIR auth yet — protected by Django session / token auth.
"""
import datetime
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone


FHIR_CONTENT_TYPE = 'application/fhir+json'


def _fhir_response(data, status=200):
    r = JsonResponse(data, status=status)
    r['Content-Type'] = FHIR_CONTENT_TYPE
    return r


class FhirMetadataView(View):
    """GET /fhir/metadata — CapabilityStatement (no auth required)."""

    def get(self, request):
        now = timezone.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        stmt = {
            'resourceType': 'CapabilityStatement',
            'status': 'active',
            'date': now,
            'kind': 'instance',
            'fhirVersion': '4.0.1',
            'format': ['application/fhir+json'],
            'rest': [{
                'mode': 'server',
                'resource': [
                    {
                        'type': 'Patient',
                        'interaction': [{'code': 'read'}],
                        'versioning': 'no-version',
                    },
                    {
                        'type': 'BiologicallyDerivedProduct',
                        'interaction': [{'code': 'read'}],
                        'versioning': 'no-version',
                    },
                    {
                        'type': 'AuditEvent',
                        'interaction': [{'code': 'search-type'}],
                        'searchParam': [
                            {'name': 'patient', 'type': 'reference'},
                            {'name': 'date', 'type': 'date'},
                        ],
                    },
                ],
            }],
        }
        return _fhir_response(stmt)


class FhirPatientView(LoginRequiredMixin, View):
    """GET /fhir/Patient/{id} — Patient resource."""
    raise_exception = True

    def get(self, request, pk):
        from patients.models import Patient
        try:
            patient = Patient.objects.select_related('subject').get(pk=pk)
        except Patient.DoesNotExist:
            return _fhir_response({'resourceType': 'OperationOutcome',
                                   'issue': [{'severity': 'error', 'code': 'not-found',
                                              'diagnostics': f'Patient {pk} not found.'}]}, 404)

        subject = patient.subject
        display_name = subject.display_name if subject else ''
        bg = patient.effective_blood_group()
        resource = {
            'resourceType': 'Patient',
            'id': str(pk),
            'meta': {'profile': ['http://hl7.org/fhir/StructureDefinition/Patient']},
            'identifier': [
                {'system': 'urn:bloodbank:mpi', 'value': str(patient.mpi_uid)},
            ],
            'name': [{'text': display_name}] if display_name else [],
            'gender': _map_sex(patient.sex),
            'birthDate': patient.dob.isoformat() if patient.dob else None,
            'extension': [],
        }
        if bg:
            resource['extension'].append({
                'url': 'http://hl7.org/fhir/StructureDefinition/patient-bloodGroup',
                'valueCodeableConcept': {
                    'coding': [{
                        'system': 'http://snomed.info/sct',
                        'display': f"{bg.abo} {bg.rh_d}",
                    }],
                    'text': f"{bg.abo} {'Rh+' if bg.rh_d == 'pos' else 'Rh-' if bg.rh_d == 'neg' else bg.rh_d}",
                },
            })
        return _fhir_response(resource)


class FhirBiologicallyDerivedProductView(LoginRequiredMixin, View):
    """GET /fhir/BiologicallyDerivedProduct/{did}"""
    raise_exception = True

    def get(self, request, did):
        from inventory.models import BloodUnit
        try:
            unit = BloodUnit.objects.select_related('component_type', 'owner_branch').get(did=did)
        except BloodUnit.DoesNotExist:
            return _fhir_response({'resourceType': 'OperationOutcome',
                                   'issue': [{'severity': 'error', 'code': 'not-found',
                                              'diagnostics': f'Unit {did} not found.'}]}, 404)

        STATUS_MAP = {
            'available': 'available',
            'quarantined': 'unavailable',
            'reserved': 'available',
            'crossmatched': 'available',
            'issued': 'unavailable',
            'expired': 'unavailable',
            'destroyed': 'unavailable',
            'discarded': 'unavailable',
        }
        resource = {
            'resourceType': 'BiologicallyDerivedProduct',
            'id': unit.did,
            'identifier': [
                {'system': 'urn:bloodbank:did', 'value': unit.did},
            ],
            'productCategory': 'biologicallyDerivedProductCategory',
            'productCode': {
                'text': unit.component_type.name if unit.component_type else unit.component_class,
            },
            'status': STATUS_MAP.get(unit.status, 'unavailable'),
            'collection': {
                'collectedDateTime': unit.collection_datetime.isoformat() if unit.collection_datetime else None,
            },
            'storage': [{
                'description': f"{unit.owner_branch.name} storage",
                'duration': {
                    'start': unit.collection_datetime.isoformat() if unit.collection_datetime else None,
                    'end': unit.expiry_datetime.isoformat() if unit.expiry_datetime else None,
                },
            }],
            'extension': [
                {'url': 'urn:bloodbank:abo', 'valueString': unit.abo_type},
                {'url': 'urn:bloodbank:rh_d', 'valueString': unit.rh_d_type},
                {'url': 'urn:bloodbank:component_class', 'valueString': unit.component_class},
            ],
        }
        return _fhir_response(resource)


class FhirAuditEventView(LoginRequiredMixin, View):
    """GET /fhir/AuditEvent?patient=&date="""
    raise_exception = True

    def get(self, request):
        from audit.models import AuditLog
        qs = AuditLog.objects.select_related('actor').order_by('-occurred_at_utc')

        patient_id = request.GET.get('patient')
        date_str   = request.GET.get('date')

        if patient_id:
            qs = qs.filter(entity_id=patient_id, entity_table__contains='patient')
        if date_str:
            try:
                d = datetime.date.fromisoformat(date_str)
                qs = qs.filter(occurred_at_utc__date=d)
            except ValueError:
                pass

        entries = []
        for log in qs[:50]:
            actor_display = (log.actor.display_name or log.actor.username) if log.actor else 'system'
            entries.append({
                'resourceType': 'AuditEvent',
                'id': str(log.pk),
                'type': {'system': 'http://dicom.nema.org/resources/ontology/DCM', 'code': '110100'},
                'recorded': log.occurred_at_utc.isoformat(),
                'outcome': '0',
                'agent': [{'who': {'display': actor_display}, 'requestor': True}],
                'source': {'site': 'BloodBankLIS'},
                'entity': [{'what': {'reference': f"{log.entity_table}/{log.entity_id}"},
                             'description': log.action}],
            })

        bundle = {
            'resourceType': 'Bundle',
            'type': 'searchset',
            'total': len(entries),
            'entry': [{'resource': e} for e in entries],
        }
        return _fhir_response(bundle)


def _map_sex(sex_code):
    return {'M': 'male', 'F': 'female', 'U': 'unknown', 'X': 'other'}.get(sex_code, 'unknown')
