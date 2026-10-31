from django.urls import path
from . import views

app_name = 'donors'

urlpatterns = [
    path('', views.donor_list, name='list'),
    path('register/', views.register_donor, name='register'),
    path('<int:pk>/', views.donor_detail, name='detail'),
    path('<int:pk>/eligibility/', views.eligibility_screen, name='eligibility'),
    path('<int:pk>/dhq/', views.dhq_create, name='dhq_create'),
    path('<int:pk>/dhq/<int:dhq_pk>/', views.dhq_detail, name='dhq_detail'),
    path('<int:pk>/donate/', views.record_donation, name='record_donation'),
    path('<int:pk>/deferral-letter.pdf', views.deferral_letter, name='deferral_letter'),
    path('donation/<int:donation_pk>/adverse-event/', views.record_adverse_event, name='record_adverse_event'),
    path('<int:pk>/lookback/', views.start_lookback, name='start_lookback'),
    path('lapsed/', views.lapsed_donors, name='lapsed_donors'),
    path('<int:pk>/phenotype/', views.record_phenotype, name='record_phenotype'),
    path('milestones/', views.donor_milestones, name='milestones'),
    path('<int:pk>/blood-group-card.pdf', views.blood_group_card_pdf, name='blood_group_card_pdf'),
    path('campaigns/', views.campaign_list, name='campaign_list'),
    path('campaigns/new/', views.campaign_create, name='campaign_create'),
    path('campaigns/<int:pk>/', views.campaign_detail, name='campaign_detail'),
    path('<int:pk>/dsr/', views.donor_dsr_view, name='dsr'),
]
