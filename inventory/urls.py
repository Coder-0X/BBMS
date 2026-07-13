from django.urls import path

from . import views

urlpatterns = [
    path('', views.InventoryListView.as_view(), name='inventory_list'),
    path('add/', views.InventoryCreateView.as_view(), name='inventory_add'),
    path(
        '<int:pk>/edit/',
        views.InventoryUpdateView.as_view(),
        name='inventory_edit',
    ),
    path(
        '<int:pk>/delete/',
        views.InventoryDeleteView.as_view(),
        name='inventory_delete',
    ),
    path(
        'components/',
        views.ComponentListView.as_view(),
        name='component_list',
    ),
    path(
        'components/add/',
        views.ComponentCreateView.as_view(),
        name='component_add',
    ),
    path(
        'components/<int:pk>/edit/',
        views.ComponentUpdateView.as_view(),
        name='component_edit',
    ),
    path(
        'components/<int:pk>/delete/',
        views.ComponentDeleteView.as_view(),
        name='component_delete',
    ),
    path('units/', views.UnitListView.as_view(), name='unit_list'),
    path('units/add/', views.UnitCreateView.as_view(), name='unit_add'),
    path(
        'units/<int:pk>/edit/',
        views.UnitUpdateView.as_view(),
        name='unit_edit',
    ),
    path(
        'units/<int:pk>/delete/',
        views.UnitDeleteView.as_view(),
        name='unit_delete',
    ),
]
