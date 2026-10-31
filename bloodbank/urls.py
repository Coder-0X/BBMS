from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/dashboard/', permanent=False)),
    path('accounts/', include('accounts.urls')),
    path('', include('core.urls')),
    path('api/v1/', include('api.urls')),
    path('donors/', include('donors.urls')),
    path('inventory/', include('inventory.urls')),
    path('patients/', include('patients.urls')),
    path('transfusion/', include('transfusion.urls')),
    path('analytics/', include('analytics.urls')),
    path('fhir/', include('api.fhir_urls')),
    path('quality/', include('quality.urls')),
    path('coldchain/', include('coldchain.urls')),
    # PWA shortcut — manifest start_url points here
    path('bedside/', RedirectView.as_view(url='/transfusion/bedside/', permanent=False)),
]
