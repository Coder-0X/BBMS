from django.urls import path

from . import views

urlpatterns = [
    path('', views.DonorListView.as_view(), name='donor_list'),
    path('add/', views.DonorCreateView.as_view(), name='donor_add'),
    path('<int:pk>/edit/', views.DonorUpdateView.as_view(), name='donor_edit'),
    path(
        '<int:pk>/delete/',
        views.DonorDeleteView.as_view(),
        name='donor_delete',
    ),
    path('donations/', views.DonationListView.as_view(), name='donation_list'),
    path(
        'donations/add/',
        views.DonationCreateView.as_view(),
        name='donation_add',
    ),
    path(
        'donations/<int:pk>/edit/',
        views.DonationUpdateView.as_view(),
        name='donation_edit',
    ),
    path(
        'donations/<int:pk>/delete/',
        views.DonationDeleteView.as_view(),
        name='donation_delete',
    ),
    path('recall/', views.DonorRecallSearchView.as_view(), name='donor_recall_search'),
    path('<int:pk>/recall/', views.DonorRecallDetailView.as_view(), name='donor_recall_detail'),
    path('<int:pk>/recall/destroy-stock/', views.DonorRecallDestroyStockView.as_view(), name='donor_recall_destroy_stock'),
]
