"""
Donation ID (DID) generation.

Format: [FAC(3)][YY(2)][SERIAL(6)][CHECK(1)] = 12 chars
Example: KNH26000001C

Check character is a Luhn digit computed over the 8-digit numeric portion
(YY + SERIAL). The facility code is validated separately against ref_facilities.
"""

import re
from datetime import date


def _luhn_check_digit(digits: str) -> str:
    """Standard Luhn check digit over a string of digits."""
    nums = [int(d) for d in digits]
    # Double every other digit from the right
    for i in range(len(nums) - 2, -1, -2):
        nums[i] *= 2
        if nums[i] > 9:
            nums[i] -= 9
    remainder = sum(nums) % 10
    return str((10 - remainder) % 10)


def generate_did(facility_code: str, serial: int, year: date = None) -> str:
    """
    Build a 12-character DID for a blood unit.

    facility_code: 3-letter code from ref_facilities (e.g. 'KNH')
    serial: integer serial number (1–999999)
    year: defaults to current year
    """
    if len(facility_code) != 3 or not facility_code.isalpha():
        raise ValueError("facility_code must be exactly 3 letters")
    if not 1 <= serial <= 999999:
        raise ValueError("serial must be between 1 and 999999")

    yy = str((year or date.today()).year)[-2:]
    serial_str = str(serial).zfill(6)
    numeric_part = yy + serial_str           # 8 digits
    check = _luhn_check_digit(numeric_part)

    return facility_code.upper() + yy + serial_str + check


def verify_did(did: str) -> bool:
    """Return True if the DID's check character is valid."""
    if not re.match(r'^[A-Z]{3}\d{8}[0-9]$', did):
        return False
    numeric_part = did[3:11]   # YY + SERIAL (8 digits) — must match generate_did,
    # which computes the check digit over the FULL 8-digit numeric part. The
    # trailing check character is did[11], NOT part of numeric_part, so do not
    # slice a digit off here (previously `numeric_part[:-1]` hashed only 7 digits,
    # making every validly-generated DID fail verification).
    expected_check = _luhn_check_digit(numeric_part)
    return did[11] == expected_check


def parse_did(did: str) -> dict:
    """Break a DID into its parts. Raises ValueError if format is wrong."""
    if not re.match(r'^[A-Z]{3}\d{8}[0-9]$', did):
        raise ValueError(f"Invalid DID format: {did}")
    return {
        'facility_code': did[:3],
        'year': '20' + did[3:5],
        'serial': int(did[5:11]),
        'check': did[11],
    }
