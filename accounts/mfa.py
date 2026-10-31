"""
TOTP multi-factor authentication helpers using pyotp.
"""
import hashlib
import secrets
import pyotp
import qrcode
import io
import base64


def generate_mfa_secret() -> str:
    return pyotp.random_base32()


def get_totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret)


def verify_totp(secret: str, code: str) -> bool:
    """Allow a ±1 window to handle minor clock drift."""
    totp = get_totp(secret)
    return totp.verify(code, valid_window=1)


def get_provisioning_uri(secret: str, username: str, issuer: str = "BloodBank") -> str:
    totp = get_totp(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def get_qr_code_base64(secret: str, username: str) -> str:
    """Return a base64-encoded PNG of the QR code for display in the setup page."""
    uri = get_provisioning_uri(secret, username)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


def generate_recovery_codes(count: int = 8) -> tuple[list[str], list[str]]:
    """
    Generate one-time recovery codes.
    Returns (plain_codes, hashed_codes) — store only the hashed ones.
    """
    plain = [secrets.token_hex(5).upper() for _ in range(count)]
    hashed = [hashlib.sha256(c.encode()).hexdigest() for c in plain]
    return plain, hashed


def verify_recovery_code(code: str, hashed_codes: list[str]) -> tuple[bool, list[str]]:
    """
    Check if the code matches one of the stored hashed codes.
    Returns (matched, remaining_hashed_codes) — used codes are removed.
    """
    code_hash = hashlib.sha256(code.upper().encode()).hexdigest()
    if code_hash in hashed_codes:
        remaining = [h for h in hashed_codes if h != code_hash]
        return True, remaining
    return False, hashed_codes
