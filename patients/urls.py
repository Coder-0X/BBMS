from django.urls import path
from . import views

app_name = 'patients'

urlpatterns = [
    path('', views.patient_list, name='list'),
    path('register/', views.register_patient, name='register'),
    path('<int:pk>/', views.patient_detail, name='detail'),
    path('<int:pk>/blood-group/add/', views.add_blood_group, name='add_blood_group'),
    path('<int:pk>/antibody/add/', views.add_antibody, name='add_antibody'),
    path('<int:pk>/requirement/add/', views.add_requirement, name='add_requirement'),
    path('<int:pk>/discrepancy/', views.investigate_discrepancy, name='investigate_discrepancy'),
    path('discrepancies/', views.discrepancy_investigation_list, name='discrepancy_list'),
    path('<int:pk>/merge/', views.merge_patient, name='merge'),
    path('<int:pk>/traceability/', views.traceability_report, name='traceability'),
    path('<int:pk>/consent/', views.record_consent, name='record_consent'),
    path('<int:pk>/consent/<int:consent_pk>/withdraw/', views.withdraw_consent, name='withdraw_consent'),
    path('<int:pk>/phenotype/', views.record_patient_phenotype, name='record_phenotype'),
    # Therapeutic Phlebotomy
    path('therapeutic-phlebotomy/', views.therapeutic_phlebotomy_list, name='tp_list'),
    path('<int:patient_pk>/therapeutic-phlebotomy/schedule/', views.therapeutic_phlebotomy_schedule, name='tp_schedule'),
    path('therapeutic-phlebotomy/<int:pk>/', views.therapeutic_phlebotomy_detail, name='tp_detail'),
    # Antenatal Anti-D Programme
    path('antenatal/', views.antenatal_list, name='antenatal_list'),
    path('<int:patient_pk>/antenatal/new/', views.antenatal_create, name='antenatal_create'),
    path('antenatal/<int:pk>/', views.antenatal_detail, name='antenatal_detail'),
    # HDFN (Haemolytic Disease of the Fetus and Newborn)
    path('hdfn/', views.hdfn_list, name='hdfn_list'),
    path('<int:mother_pk>/hdfn/new/', views.hdfn_create, name='hdfn_create'),
    path('hdfn/<int:pk>/', views.hdfn_detail, name='hdfn_detail'),
    # Blood Group Card PDF
    path('<int:pk>/bg-card.pdf', views.patient_blood_group_card_pdf, name='bg_card_pdf'),
]
