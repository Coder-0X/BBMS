"""Project URL configuration."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('donors/', include('donors.urls')),
    path('lab/', include('lab.urls')),
    path('inventory/', include('inventory.urls')),
    path('patients/', include('patients.urls')),
    path('staff/', include('staff.urls')),
]
