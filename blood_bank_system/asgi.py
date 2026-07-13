"""ASGI config for blood_bank_system project."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blood_bank_system.settings')

application = get_asgi_application()
