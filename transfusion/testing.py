"""
TTI test result recording.

Record a single infectious disease test result for a donation.
If the result is reactive, all units from that donation are automatically quarantined.
The DonationTestResult.save() handles the auto-quarantine, but this module
wraps it with signature and audit requirements.
"""
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from audit.utils import write_audit, create_signature


@transaction.atomic
def record_test_result(donation, test_code, sample, result,
                       performed_by, reviewed_by, reauth_at,
                       instrument='', instrument_lot='', s_co_ratio=None):
    """
    Record a TTI result and create required e-signatures.

    If result == 'reactive', units from this donation are auto-quarantined
    inside DonationTestResult.save().

    Returns the DonationTestResult.
    """
    from transfusion.models import TestDefinition, DonationTestResult

    try:
        test = TestDefinition.objects.get(test_code=test_code)
    except TestDefinition.DoesNotExist:
        raise ValidationError(
            f"Test code '{test_code}' is not defined in the system. "
            f"Contact the laboratory manager to add it."
        )

    # Reviewer must e-sign the test result
    payload = {
        'donation_id': donation.pk,
        'test_code': test_code,
        'result': result,
        'performed_at': timezone.now().isoformat(),
        'performed_by': performed_by.username,
        'reviewed_by': reviewed_by.username,
    }
    esign = create_signature(
        signer=reviewed_by,
        meaning='tti_test_review',
        payload_data=payload,
        reauth_at=reauth_at,
    )

    test_result = DonationTestResult.objects.create(
        donation=donation,
        test=test,
        sample=sample,
        result=result,
        instrument=instrument,
        instrument_lot=instrument_lot,
        s_co_ratio=s_co_ratio,
        performed_by=performed_by,
        reviewed_by=reviewed_by,
        esign=esign,
        performed_at=timezone.now(),
    )

    write_audit(
        actor=reviewed_by,
        action='donation.test_result',
        entity_table='transfusion_donationtestresult',
        entity_id=test_result.pk,
        after=payload,
        action_meaning=f"Donation #{donation.pk} / {test_code}: {result}",
        branch=sample.branch,
    )

    return test_result
