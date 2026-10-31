from django.db import models
from django.conf import settings


class AuditLog(models.Model):
    """
    Append-only, hash-chained record of every safety-critical action.

    Never UPDATE or DELETE rows here. The application DB user should only have
    INSERT + SELECT on this table. The hash chain makes tampering detectable.
    """
    seq = models.BigIntegerField(unique=True)
    occurred_at_utc = models.DateTimeField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='audit_entries',
    )
    action = models.CharField(max_length=100)       # e.g. 'unit.status_changed'
    action_meaning = models.CharField(max_length=500, blank=True)
    entity_table = models.CharField(max_length=100)
    entity_id = models.BigIntegerField()
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    branch = models.ForeignKey(
        'core.Branch',
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )
    source = models.CharField(
        max_length=20,
        choices=[('online', 'Online'), ('offline_replay', 'Offline Replay')],
        default='online',
    )
    prev_hash = models.CharField(max_length=64)
    row_hash = models.CharField(max_length=64)

    # Set after electronic_signatures is ready
    esign = models.ForeignKey(
        'audit.ElectronicSignature',
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='+',
    )

    class Meta:
        ordering = ['seq']

    def __str__(self):
        return f"[{self.seq}] {self.action} on {self.entity_table}:{self.entity_id}"


class AuditChainAnchor(models.Model):
    """
    Periodic external proof that the audit chain hasn't been tampered with.
    Even a DBA can't falsify history without diverging from the stored anchors.
    """
    chain_head_hash = models.CharField(max_length=64)
    chain_head_seq = models.BigIntegerField()
    anchored_at = models.DateTimeField(auto_now_add=True)
    # RFC 3161 timestamp token from FreeTSA.org (base64 encoded)
    tsa_token = models.TextField(blank=True)
    # Our own server's signature of the hash
    server_signature = models.TextField(blank=True)

    def __str__(self):
        return f"Anchor @ seq={self.chain_head_seq} ({self.anchored_at:%Y-%m-%d})"


class ElectronicSignature(models.Model):
    """
    A user's digital sign-off on a specific action.
    The signed_payload_hash binds this signature to the exact record content —
    it can't be lifted and attached to a different record.
    """
    MEANINGS = [
        ('reviewed', 'Reviewed'),
        ('approved', 'Approved'),
        ('released', 'Released'),
        ('verified', 'Verified'),
        ('quarantine_release', 'Quarantine Release'),
        ('recalled', 'Recalled'),
        ('rejected', 'Rejected'),
        ('witnessed', 'Witnessed'),
    ]

    signer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='signatures',
    )
    signed_at_utc = models.DateTimeField()
    meaning = models.CharField(max_length=30, choices=MEANINGS)
    auth_method = models.CharField(
        max_length=20,
        choices=[('password_reauth', 'Password Re-auth'), ('mfa_reauth', 'MFA Re-auth')],
    )
    reauth_at = models.DateTimeField()
    # SHA-256 of the record being signed
    signed_payload_hash = models.CharField(max_length=64)
    audit_log = models.ForeignKey(
        AuditLog, null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='signatures',
    )
    # Printed name at the time of signing (for paper-equivalent display)
    manifested_name = models.CharField(max_length=200)

    def __str__(self):
        return f"{self.manifested_name} — {self.get_meaning_display()} @ {self.signed_at_utc:%Y-%m-%d %H:%M}"
