from django.urls import path

from . import views

urlpatterns = [
    path('', views.BloodTestListView.as_view(), name='lab_list'),
    path('add/', views.BloodTestCreateView.as_view(), name='lab_add'),
    path(
        '<int:pk>/edit/',
        views.BloodTestUpdateView.as_view(),
        name='lab_edit',
    ),
    path(
        '<int:pk>/delete/',
        views.BloodTestDeleteView.as_view(),
        name='lab_delete',
    ),
]
