"""
Test-specific settings. Overrides production settings for speed and isolation.
"""
import os
from bloodbank.settings import *  # noqa: F401,F403

# Fast password hashing for tests
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Test database — PostgreSQL required (SQLite cannot handle case-differentiated
# column names C/c used in blood group phenotype migrations).
# Run `python create_test_db.py` once to create the test DB and grant permissions.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('TEST_DB_NAME', 'bloodbank_test'),
        'USER': os.getenv('DB_USER', 'bloodbank_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'luckycharm'),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'TEST': {'NAME': os.getenv('TEST_DB_NAME', 'bloodbank_test')},
    }
}

# Use a fixed, deterministic secret key so encryption is reproducible in tests
SECRET_KEY = 'test-secret-key-deterministic-for-tests-bloodbank-lis-2026'

# Use a fixed encryption key (32 bytes hex) — dev only
os.environ.setdefault('ENCRYPTION_KEY', 'a' * 64)
os.environ.setdefault('BLIND_INDEX_KEY', 'b' * 64)

# Disable real email
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Disable Vault (use local key derivation)
VAULT_URL = ''
VAULT_TOKEN = ''

# Disable session middleware that reads DB for every request
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Speed up tests — no real media files needed
DEFAULT_FILE_STORAGE = 'django.core.files.storage.InMemoryStorage'

# Disable debug toolbar and other dev middleware
INSTALLED_APPS = [a for a in INSTALLED_APPS if 'debug_toolbar' not in a]
MIDDLEWARE = [m for m in MIDDLEWARE if 'debug_toolbar' not in m]

# Silence migration output
class DisableMigrations:
    def __contains__(self, item):
        return True
    def __getitem__(self, item):
        return None

# Comment out to use real migrations (needed for DB constraint tests)
# MIGRATION_MODULES = DisableMigrations()
