"""
Data Subject Rights (DSR) handler for blood bank LIS.

CRITICAL LEGAL CONTEXT — BLOOD BANK RETENTION OBLIGATIONS
===========================================================
Blood bank records are subject to mandatory statutory retention periods that
*override* GDPR Article 17 (right to erasure):

  EU Blood Directive 2002/98/EC, Annex VI:
    → Minimum 30 years for all donor/recipient traceability records.

  FDA 21 CFR Part 606.160:
    → Minimum 10 years (or 6 months past expiry, whichever is later).

  MHRA / Blood Safety and Quality Regulations 2005 (UK):
    → Minimum 30 years.

  GDPR Article 17(3)(b): The right to erasure does NOT apply when
    processing is necessary to comply with a legal obligation (here:
    the Blood Directive and national implementing legislation).

  GDPR Article 17(3)(c): The right to erasure does NOT apply when
    processing is necessary for reasons of public interest in the
    area of public health (GDPR Art 9(2)(i)).

WHAT THIS MODULE DOES
=====================
handle_erasure_request(dsr_request)
  1. Checks whether the subject has blood-safety records (donations,
     issue transactions, crossmatch, TTI results).
  2. If YES  → Legal refusal: cite statute, update DSR status to 'refused'.
               Still erases marketing-only data (campaign enrollments,
               outreach contact_enc if the donation record carries the link).
  3. If NO   → Full pseudonymisation: blank name_enc / national_id_enc /
               contact_enc and remove from campaign enrollments.

In both cases:
  - Withdrawal of outreach/marketing consent is honoured immediately.
  - Withdrawal of healthcare/vital-interest consent does not erase records;
    it means no *future* transfusions can be authorised without a new consent.

REFERENCES
==========
  Commission Directive 2004/33/EC; GDPR Recitals 52, 65, 73;
  UK Data Protection Act 2018 Schedule 3 paragraph 2; WHO Blood Safety 2010.
"""
from django.utils import timezone


BLOOD_SAFETY_RETENTION_STATEMENT = (
    "Blood bank traceability records must be retained for a minimum of 30 years "
    "under EU Blood Directive 2002/98/EC (Annex VI) and equivalent national law. "
    "This legal obligation takes precedence over the GDPR Article 17 right to erasure "
    "pursuant to GDPR Article 17(3)(b). "
    "Additionally, GDPR Article 17(3)(c) disapplies the right to erasure where "
    "processing is necessary for public health purposes (GDPR Art 9(2)(i)). "
    "Blood safety records — including donation history, infectious disease test results, "
    "crossmatch records, and donor-to-recipient traceability — cannot be erased. "
    "We have removed your contact/marketing data and campaign enrollments. "
    "No further outreach will be sent."
)


def has_blood_safety_records(subject) -> bool:
    """
    Returns True if this subject has any blood-safety records that must be
    retained under the Blood Directive 30-year rule.
    """
    # Donor pathway: any donations made
    if subject.subject_type == 'donor':
        try:
            donor = subject.donor
            if donor.total_donations > 0:
                return True
            # Check actual Donation records even if counter is stale
            from donors.models import Donation
            if Donation.objects.filter(donor=donor).exists():
                return True
            # Check TTI test results
            from transfusion.models import DonationTestResult
            if DonationTestResult.objects.filter(donation__donor=donor).exists():
                return True
        except Exception:
            # Fail-safe: if the lookup itself errors, assume blood-safety records
            # exist to prevent accidental erasure of retained data.
            return True

    # Patient pathway: any blood received or crossmatched
    if subject.subject_type == 'patient':
        try:
            patient = subject.patient
            from transfusion.models import IssueTransaction, BloodRequest
            if IssueTransaction.objects.filter(patient=patient).exists():
                return True
            if BloodRequest.objects.filter(patient=patient).exists():
                return True
        except Exception:
            # Fail-safe: if the lookup itself errors, assume blood-safety records
            # exist to prevent accidental erasure of retained data.
            return True

    return False


def erase_marketing_data(subject, actor=None) -> dict:
    """
    Remove data that is not subject to blood-safety retention:
      - Campaign enrollments
      - ConsentRecord rows with lawful_basis='consent' (outreach/marketing)
      - contact_enc (replace with a tombstone so the record still exists
        but carries no personal contact data; the blood-safety records
        that reference subject_id remain intact)

    Returns a dict summarising what was erased.
    """
    erased = {}

    # 1. Remove from retention campaigns
    if subject.subject_type == 'donor':
        try:
            from donors.models import CampaignEnrollment
            count, _ = CampaignEnrollment.objects.filter(donor=subject.donor).delete()
            erased['campaign_enrollments_deleted'] = count
        except Exception:
            erased['campaign_enrollments_deleted'] = 0

    # 2. Withdraw all outreach/marketing consent records
    withdrawn = subject.consents.filter(
        lawful_basis='consent',
        withdrawn_at__isnull=True,
    )
    wcount = withdrawn.count()
    withdrawn.update(
        withdrawn_at=timezone.now(),
        withdrawal_note='Automatically withdrawn on erasure request (GDPR Art 17).',
    )
    erased['consent_records_withdrawn'] = wcount

    # 3. Blank contact_enc — outreach data, not needed for traceability
    if subject.contact_enc:
        subject.contact_enc = ''
        subject.save(update_fields=['contact_enc'])
        erased['contact_enc_cleared'] = True

    return erased


def pseudonymise_identity(subject, actor=None) -> dict:
    """
    Full pseudonymisation for subjects with NO blood-safety records.
    Blanks all encrypted PII fields and blind indexes.
    The row itself is kept (foreign keys from other tables may reference it)
    but contains no recoverable personal data.
    """
    subject.name_enc = ''
    subject.national_id_enc = ''
    subject.contact_enc = ''
    subject.name_blind_index = ''
    subject.national_id_blind_index = ''
    subject.save(update_fields=[
        'name_enc', 'national_id_enc', 'contact_enc',
        'name_blind_index', 'national_id_blind_index',
    ])
    return {'identity_pseudonymised': True}


def handle_erasure_request(dsr_request, actor=None) -> dict:
    """
    Main entry point. Call after a DSRRequest of type='erase' is created.

    Returns a summary dict of what was done.
    Marks the DSRRequest as completed (or refused) and sets outcome.
    """
    from .models import DSRRequest
    assert dsr_request.request_type == 'erase', "Only call this for erase requests."

    subject = dsr_request.subject
    result = {}

    if has_blood_safety_records(subject):
        # Legal refusal — cannot erase blood-safety records
        result['decision'] = 'partial_erasure_legal_refusal'
        result['statute'] = 'EU Blood Directive 2002/98/EC Annex VI (30-year retention); GDPR Art 17(3)(b)/(c)'

        # Still erase what we legally can
        marketing_erased = erase_marketing_data(subject, actor=actor)
        result['marketing_erased'] = marketing_erased

        dsr_request.status = 'refused'
        dsr_request.refusal_reason = BLOOD_SAFETY_RETENTION_STATEMENT
        dsr_request.outcome = (
            f"Partial erasure performed. Blood-safety traceability records retained "
            f"under legal obligation. Marketing data removed: {marketing_erased}"
        )
    else:
        # No blood-safety records — full pseudonymisation is lawful
        result['decision'] = 'full_pseudonymisation'

        marketing_erased = erase_marketing_data(subject, actor=actor)
        id_result = pseudonymise_identity(subject, actor=actor)
        result['marketing_erased'] = marketing_erased
        result['identity_result'] = id_result

        dsr_request.status = 'completed'
        dsr_request.outcome = (
            f"Full pseudonymisation performed (no blood-safety records found). "
            f"All PII fields blanked. {marketing_erased}"
        )

    dsr_request.completed_at = timezone.now()
    if actor:
        dsr_request.handled_by = actor
    dsr_request.save(update_fields=['status', 'refusal_reason', 'outcome', 'completed_at', 'handled_by'])

    return result


def handle_access_request(dsr_request, actor=None) -> dict:
    """
    GDPR Art 15 — right of access. Returns a structured summary of what data
    we hold about this subject. The caller is responsible for formatting it
    (e.g., rendering a PDF report for the subject).

    Blood-safety records are included in the access response (the subject
    has the right to KNOW what we hold, even if they cannot demand erasure).
    """
    subject = dsr_request.subject
    held = {
        'subject_type': subject.subject_type,
        'has_encrypted_name': bool(subject.name_enc),
        'has_encrypted_national_id': bool(subject.national_id_enc),
        'has_encrypted_contact': bool(subject.contact_enc),
        'blood_safety_records': has_blood_safety_records(subject),
        'consent_records': list(
            subject.consents.values('purpose', 'lawful_basis', 'captured_at', 'withdrawn_at')
        ),
    }

    if subject.subject_type == 'donor':
        try:
            donor = subject.donor
            held['total_donations'] = donor.total_donations
            held['blood_group'] = f"{donor.blood_group_abo} {donor.blood_group_rh}"
            held['deferral_status'] = donor.deferral_status
        except Exception:
            pass

    dsr_request.status = 'completed'
    dsr_request.outcome = f"Access report generated. Data held summary: {held}"
    dsr_request.completed_at = timezone.now()
    if actor:
        dsr_request.handled_by = actor
    dsr_request.save(update_fields=['status', 'outcome', 'completed_at', 'handled_by'])

    return held
