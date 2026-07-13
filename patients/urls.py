from django.urls import path

from . import views

urlpatterns = [
    path('', views.PatientListView.as_view(), name='patient_list'),
    path('add/', views.PatientCreateView.as_view(), name='patient_add'),
    path(
        '<int:pk>/edit/',
        views.PatientUpdateView.as_view(),
        name='patient_edit',
    ),
    path(
        '<int:pk>/delete/',
        views.PatientDeleteView.as_view(),
        name='patient_delete',
    ),
    path('requests/', views.RequestListView.as_view(), name='request_list'),
    path(
        'requests/add/',
        views.RequestCreateView.as_view(),
        name='request_add',
    ),
    path(
        'requests/<int:pk>/edit/',
        views.RequestUpdateView.as_view(),
        name='request_edit',
    ),
    path(
        'requests/<int:pk>/delete/',
        views.RequestDeleteView.as_view(),
        name='request_delete',
    ),
    path(
        'crossmatches/',
        views.CrossmatchListView.as_view(),
        name='crossmatch_list',
    ),
    path(
        'crossmatches/add/',
        views.CrossmatchCreateView.as_view(),
        name='crossmatch_add',
    ),
    path(
        'crossmatches/<int:pk>/edit/',
        views.CrossmatchUpdateView.as_view(),
        name='crossmatch_edit',
    ),
    path(
        'crossmatches/<int:pk>/delete/',
        views.CrossmatchDeleteView.as_view(),
        name='crossmatch_delete',
    ),
    path('issues/', views.IssueListView.as_view(), name='issue_list'),
    path('issues/add/', views.IssueCreateView.as_view(), name='issue_add'),
    path(
        'issues/<int:pk>/edit/',
        views.IssueUpdateView.as_view(),
        name='issue_edit',
    ),
    path(
        'issues/<int:pk>/delete/',
        views.IssueDeleteView.as_view(),
        name='issue_delete',
    ),
]
