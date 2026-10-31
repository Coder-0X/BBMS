from django.urls import path
from . import fhir_views

urlpatterns = [
    path('metadata', fhir_views.FhirMetadataView.as_view(), name='fhir_metadata'),
    path('Patient/<int:pk>', fhir_views.FhirPatientView.as_view(), name='fhir_patient'),
    path('BiologicallyDerivedProduct/<str:did>', fhir_views.FhirBiologicallyDerivedProductView.as_view(), name='fhir_bdp'),
    path('AuditEvent', fhir_views.FhirAuditEventView.as_view(), name='fhir_audit_event'),
]
