from django.contrib import admin

from .models import BloodComponent, BloodUnit, Inventory

admin.site.register(BloodComponent)
admin.site.register(BloodUnit)
admin.site.register(Inventory)
