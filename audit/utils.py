"""
Audit log utilities: hash chain computation, writing audit entries,
creating electronic signatures.
"""
import hashlib
import json
from django.db import transaction
from django.utils import timezone


def _compute_row_hash(seq, occurred_at, actor_id, action, entity_table, entity_id,
                      before_json, after_json, prev_hash) -> str:
    parts = [
        str(seq),
        occurred_at.isoformat(),
        str(actor_id),
        action,
        entity_table,
        str(entity_id),
        json.dumps(before_json, sort_keys=True, default=str) if before_json else '',
        json.dumps(after_json, sort_keys=True, default=str) if after_json else '',
        prev_hash,
    ]
    payload = '|'.join(parts)
    return hashlib.sha256(payload.encode()).hexdigest()


def _payload_hash(data: dict) -> str:
    """Hash the content of a record for electronic signature binding."""
    payload = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def write_audit(actor, action, entity_table, entity_id,
                before=None, after=None, branch=None,
                action_meaning='', source='online') -> 'AuditLog':
    """
    Write one append-only, hash-chained audit entry.
    Must be called inside a transaction alongside the change it's recording.
    """
    from .models import AuditLog

    with transaction.atomic():
        # Get the previous row's hash (or genesis hash if this is the first row)
        last = AuditLog.objects.select_for_update().order_by('-seq').first()
        prev_hash = last.row_hash if last else ('0' * 64)
        seq = (last.seq + 1) if last else 1
        now = timezone.now()

        row_hash = _compute_row_hash(
            seq, now, actor.pk, action, entity_table, entity_id,
            before, after, prev_hash,
        )

        entry = AuditLog.objects.create(
            seq=seq,
            occurred_at_utc=now,
            actor=actor,
            action=action,
            action_meaning=action_meaning,
            entity_table=entity_table,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
            branch=branch,
            source=source,
            prev_hash=prev_hash,
            row_hash=row_hash,
        )
        return entry


def create_signature(signer, meaning, payload_data: dict,
                     audit_entry=None, reauth_at=None) -> 'ElectronicSignature':
    """
    Create an electronic signature bound to the given payload.
    The caller must ensure the user re-authenticated before calling this.
    """
    from .models import ElectronicSignature

    return ElectronicSignature.objects.create(
        signer=signer,
        signed_at_utc=timezone.now(),
        meaning=meaning,
        auth_method='password_reauth',
        reauth_at=reauth_at or timezone.now(),
        signed_payload_hash=_payload_hash(payload_data),
        audit_log=audit_entry,
        manifested_name=signer.display_name,
    )


def verify_chain() -> tuple[bool, str]:
    """
    Walk the full audit chain and check every hash.
    Returns (is_valid, message).
    """
    from .models import AuditLog

    prev_hash = '0' * 64
    for entry in AuditLog.objects.order_by('seq'):
        expected = _compute_row_hash(
            entry.seq, entry.occurred_at_utc, entry.actor_id,
            entry.action, entry.entity_table, entry.entity_id,
            entry.before_json, entry.after_json, prev_hash,
        )
        if expected != entry.row_hash:
            return False, f"Chain broken at seq={entry.seq}"
        prev_hash = entry.row_hash

    return True, "Chain is intact"
