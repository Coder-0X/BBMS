"""
Haemovigilance — transfusion reaction recording.

TransfusionReaction model lives in transfusion/models.py.
This module provides the business logic for recording and flagging reactions.
"""
from django.db import transaction
from django.utils import timezone

from audit.utils import write_audit, create_signature


@transaction.atomic
def record_reaction(issue_transaction, reaction_type, onset_datetime, severity,
                    imputability, outcome, clinical_description, actor, reauth_at,
                    investigation_summary=''):
    """
    Record a transfusion reaction.
    For Grade 3+ reactions: automatically raises a critical alert.
    Returns the TransfusionReaction instance.
    """
    from transfusion.models import TransfusionReaction

    esign = create_signature(
        signer=actor,
        meaning='transfusion_reaction_record',
        payload_data={
            'issue_transaction_id': issue_transaction.pk,
            'reaction_type': reaction_type,
            'severity': severity,
            'blood_unit_did': issue_transaction.blood_unit.did,
        },
        reauth_at=reauth_at,
    )

    reaction = TransfusionReaction.objects.create(
        issue_transaction=issue_transaction,
        patient=issue_transaction.patient,
        blood_unit=issue_transaction.blood_unit,
        reaction_type=reaction_type,
        onset_datetime=onset_datetime,
        severity=severity,
        imputability=imputability,
        outcome=outcome,
        clinical_description=clinical_description,
        investigation_summary=investigation_summary,
        recorded_by=actor,
        esign=esign,
    )

    # Grade 3+ → raise a critical alert for the responsible branch
    if severity in ('grade_3', 'grade_4', 'grade_5'):
        _raise_reaction_alert(reaction)

    write_audit(
        actor=actor,
        action='reaction.record',
        entity_table='transfusion_transfusionreaction',
        entity_id=reaction.pk,
        after={
            'reaction_type': reaction_type,
            'severity': severity,
            'unit_did': issue_transaction.blood_unit.did,
        },
        action_meaning=f"Transfusion reaction recorded: {reaction_type} ({severity})",
        branch=issue_transaction.intended_branch,
    )
    return reaction


def _raise_reaction_alert(reaction):
    from core.models import Alert
    Alert.objects.get_or_create(
        branch=reaction.blood_unit.owner_branch,
        alert_type='pending_emergency_review',
        entity_table='transfusion_transfusionreaction',
        entity_id=reaction.pk,
        acknowledged_at=None,
        defaults={
            'severity': 'critical',
            'message': (
                f"Grade {reaction.severity[-1]}+ transfusion reaction on unit {reaction.blood_unit.did}. "
                f"Type: {reaction.get_reaction_type_display()}. Immediate investigation required."
            ),
        }
    )
