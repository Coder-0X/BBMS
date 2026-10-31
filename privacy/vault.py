"""
Encryption helpers using HashiCorp Vault for key management.

In dev (VAULT_URL not set), falls back to a local key derived from SECRET_KEY.
In production, Vault holds the master key and this module wraps/unwraps data keys.
"""
import os
import base64
import hashlib
import hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

_DEV_KEY = hashlib.sha256(settings.SECRET_KEY.encode()).digest()


def _get_master_key() -> bytes:
    """Get master key from Vault, or fallback to dev key."""
    vault_url = getattr(settings, 'VAULT_URL', '')
    vault_token = getattr(settings, 'VAULT_TOKEN', '')

    if vault_url and vault_token:
        import urllib.request
        import json
        req = urllib.request.Request(
            f"{vault_url}/v1/secret/data/bloodbank/master_key",
            headers={'X-Vault-Token': vault_token},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            key_b64 = data['data']['data']['key']
            return base64.b64decode(key_b64)

    return _DEV_KEY


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a base64 ciphertext."""
    if not plaintext:
        return ''
    key = _get_master_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    combined = nonce + ciphertext
    return base64.b64encode(combined).decode()


def decrypt(ciphertext_b64: str) -> str:
    """Decrypt a base64 ciphertext back to plaintext."""
    if not ciphertext_b64:
        return ''
    key = _get_master_key()
    aesgcm = AESGCM(key)
    combined = base64.b64decode(ciphertext_b64)
    nonce = combined[:12]
    ciphertext = combined[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode()


def blind_index(value: str) -> str:
    """
    HMAC-SHA256 of a normalized value for exact-match lookup
    without decrypting the field.
    """
    if not value:
        return ''
    key = _get_master_key()
    normalized = value.strip().lower()
    return hmac.new(key, normalized.encode(), hashlib.sha256).hexdigest()
