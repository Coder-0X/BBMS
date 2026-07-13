from django.contrib import admin

from .models import Donation, Donor

admin.site.register(Donor)
admin.site.register(Donation)
