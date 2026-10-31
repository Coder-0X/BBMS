from django.urls import path
from . import views

app_name = 'coldchain'

urlpatterns = [
    path('equipment/', views.equipment_list, name='equipment_list'),
    path('equipment/<int:pk>/', views.equipment_detail, name='equipment_detail'),
    path('excursions/', views.excursion_list, name='excursion_list'),
    path('excursions/<int:pk>/resolve/', views.excursion_resolve, name='excursion_resolve'),
    path('return-check/<int:issue_pk>/', views.unit_return_check, name='unit_return_check'),
    path('return-checks/', views.return_check_list, name='return_check_list'),
]
