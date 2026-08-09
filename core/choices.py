"""Shared dropdown choices used across the blood bank apps.

Centralising these avoids free-typed values like 'a positive' or 'O+ '
sneaking into the database and breaking exact-match lookups (crossmatch
searches, expiry calculations, etc. all rely on these being consistent).
"""

# ABO blood group
ABO_CHOICES = [
    ('A', 'A'),
    ('B', 'B'),
    ('AB', 'AB'),
    ('O', 'O'),
]

# Rh factor. 'Null' covers the very rare Rh-null phenotype.
RH_CHOICES = [
    ('+', 'Positive (+)'),
    ('-', 'Negative (-)'),
    ('Null', 'Rh-null'),
]

GENDER_CHOICES = [
    ('Male', 'Male'),
    ('Female', 'Female'),
    ('Other', 'Other'),
]

# Staff roles. Each maps to which apps/actions a logged-in user can use.
# 'Admin' (or any Django superuser) can access everything, including
# Staff management itself.
ROLE_BOOTH = 'Booth'
ROLE_LAB = 'Lab'
ROLE_INVENTORY = 'Inventory'
ROLE_TRANSFUSION = 'Transfusion'
ROLE_ADMIN = 'Admin'

STAFF_ROLE_CHOICES = [
    (ROLE_BOOTH, 'Booth Staff - Register donors & record donations'),
    (ROLE_LAB, 'Lab Staff - Run blood tests, book & verify crossmatches'),
    (ROLE_INVENTORY, 'Inventory Staff - Manage blood units & components'),
    (ROLE_TRANSFUSION, 'Transfusion/Patient Staff - Requests & issuing'),
    (ROLE_ADMIN, 'Admin - Full access, including staff management'),
]

# Standard blood-component types. Shelf life / mL-per-unit for each are
# stored on the BloodComponent model (seeded via migration) so they stay
# editable without a code change.
COMPONENT_WHOLE_BLOOD = 'Whole Blood'
COMPONENT_RBC = 'Packed Red Blood Cells'
COMPONENT_PLASMA = 'Fresh Frozen Plasma'
COMPONENT_PLATELETS = 'Platelets'
COMPONENT_CRYO = 'Cryoprecipitate'

COMPONENT_NAME_CHOICES = [
    (COMPONENT_WHOLE_BLOOD, COMPONENT_WHOLE_BLOOD),
    (COMPONENT_RBC, COMPONENT_RBC),
    (COMPONENT_PLASMA, COMPONENT_PLASMA),
    (COMPONENT_PLATELETS, COMPONENT_PLATELETS),
    (COMPONENT_CRYO, COMPONENT_CRYO),
]

COMPONENT_ABBREVIATIONS = {
    COMPONENT_WHOLE_BLOOD: 'WB',
    COMPONENT_RBC: 'RBC',
    COMPONENT_PLASMA: 'FFP',
    COMPONENT_PLATELETS: 'PLT',
    COMPONENT_CRYO: 'CRYO',
}

DONATION_STATUS_CHOICES = [
    ('Collected', 'Collected'),
    ('Testing', 'Testing'),
    ('Passed', 'Passed - Units Released to Inventory'),
    ('Rejected', 'Rejected - Failed Screening'),
    ('Discarded', 'Discarded'),
]

TEST_RESULT_CHOICES = [
    ('Negative', 'Negative'),
    ('Positive', 'Positive'),
    ('Pending', 'Pending'),
]

OVERALL_RESULT_CHOICES = [
    ('Pending', 'Pending'),
    ('Pass', 'Pass'),
    ('Fail', 'Fail'),
]

UNIT_STATE_CHOICES = [
    ('Available', 'Available'),
    ('Reserved', 'Reserved'),
    ('Issued', 'Issued'),
    ('Expired', 'Expired'),
    ('Discarded', 'Discarded'),
]

REQUEST_STATUS_CHOICES = [
    ('Pending', 'Pending - Awaiting Match'),
    ('Booked', 'Booked - Unit Reserved'),
    ('Fulfilled', 'Fulfilled'),
    ('Cancelled', 'Cancelled'),
]

CROSSMATCH_STATUS_CHOICES = [
    ('Booked', 'Booked - Awaiting Test'),
    ('Passed', 'Passed - Ready to Issue'),
    ('Failed', 'Failed - Incompatible'),
    ('Released', 'Released - Reservation Expired'),
    ('Issued', 'Issued'),
]

COMPATIBILITY_RESULT_CHOICES = [
    ('Pending', 'Pending'),
    ('Compatible', 'Compatible'),
    ('Incompatible', 'Incompatible'),
]

ISSUE_STATUS_CHOICES = [
    ('Issued', 'Issued'),
    ('Returned', 'Returned'),
    ('Cancelled', 'Cancelled'),
]

# Hemoglobin cutoff (g/dL). Flat cutoff for everyone, as instructed.
HEMOGLOBIN_FAIL_CUTOFF = 12.5

# Crossmatch reservation window before an unissued booking auto-releases.
CROSSMATCH_RESERVATION_HOURS = 48

# Standard whole-blood donation bag size used as the base "1 unit" reference.
STANDARD_DONATION_ML = 450
