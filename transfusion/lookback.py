"""
Lookback campaign domain logic.

When a donor tests positive for a TTI marker (HIV, HBV, HCV, HTLV, syphilis, etc.),
all prior recipients of that donor's blood must be notified so they can be tested.
This is a legal requirement under FDA 21 CFR 606.170, EU Directive 2002/98/EC,
and NHS/SHOT guidance.

Lookback window:
- HIV, HCV, HTLV: all donations (donor's entire history at this facility)
- HBV: last 12 months (per FDA; SHOT recommends full history)
- Syphilis: last 3 months (short window, low transmission risk from stored blood)

We apply the most conservative (full history) by default.
"""
from django.db import transaction
from django.utils import timezone


@transaction.atomic
def create_lookback_campaign(donor, triggered_by_test, actor, lookback_from=None, notes=''):
    """
    Create a LookbackCampaign and auto-populate LookbackNotification rows
    for every patient who received blood from this donor.

    Returns (campaign, notifications_created).
    """
    from .models import LookbackCampaign, LookbackNotification, IssueTransaction
    from inventory.models import BloodUnit
    from audit.utils import write_audit
    import datetime

    # Default lookback window: donor's first ever donation
    if lookback_from is None:
        earliest = donor.donations.order_by('donation_date').values_list('donation_date', flat=True).first()
        lookback_from = earliest if earliest else datetime.date(2000, 1, 1)

    campaign = LookbackCampaign.objects.create(
        donor=donor,
        triggered_by_test=triggered_by_test,
        triggered_at=timezone.now(),
        initiated_by=actor,
        lookback_from=lookback_from,
        status='open',
        notes=notes,
    )

    # Find all blood units from this donor's donations
    unit_pks = list(
        BloodUnit.objects.filter(
            donation__donor=donor,
            donation__donation_date__gte=lookback_from,
        ).values_list('pk', flat=True)
    )

    # Find all issue transactions for those units
    issued_txs = IssueTransaction.objects.filter(
        blood_unit_id__in=unit_pks,
    ).select_related('patient', 'blood_unit')

    notifications_created = 0
    seen_patients = set()
    for tx in issued_txs:
        # One notification per patient per campaign (not per unit)
        if tx.patient_id in seen_patients:
            continue
        seen_patients.add(tx.patient_id)

        LookbackNotification.objects.create(
            campaign=campaign,
            patient=tx.patient,
            issue_tx=tx,
            unit_did=tx.blood_unit.did,
            transfusion_date=tx.issued_at.date(),
            status='pending',
        )
        notifications_created += 1

    write_audit(
        actor=actor,
        action='lookback.campaign.created',
        entity_table='transfusion_lookbackcampaign',
        entity_id=campaign.pk,
        after={
            'donor': donor.pk,
            'test': triggered_by_test,
            'recipients_identified': notifications_created,
        },
    )

    return campaign, notifications_created
