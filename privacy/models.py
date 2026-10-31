from django.db import models
from django.conf import settings


class SubjectIdentity(models.Model):
    """
    Encrypted personal identifiers, separated from operational tables.
    Operational records (donors, patients) reference subject_id as a pseudonym.
    Direct identifiers are AES-256-GCM encrypted via the vault module.
    """
    SUBJECT_TYPES = [('donor', 'Donor'), ('patient', 'Patient')]

    subject_type = models.CharField(max_length=10, choices=SUBJECT_TYPES, default='patient')
    # Encrypted fields — store ciphertext, decrypt via privacy.vault
    name_enc = models.TextField(blank=True)
    national_id_enc = models.TextField(blank=True)
    contact_enc = models.TextField(blank=True)
    # HMAC blind indexes for exact-match lookup without decrypting
    name_blind_index = models.CharField(max_length=64, blank=True, db_index=True)
    national_id_blind_index = models.CharField(max_length=64, blank=True, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def display_name(self) -> str:
        """Decrypt and return the subject's name (cached per instance)."""
        if not self.name_enc:
            return f'Subject #{self.pk}'
        if not hasattr(self, '_name_cache'):
            from privacy.vault import decrypt
            self._name_cache = decrypt(self.name_enc)
        return self._name_cache

    @classmethod
    def create_from_plain(cls, name, national_id, contact, subject_type, created_by):
        """Encrypt PII and create a SubjectIdentity record."""
        from privacy.vault import encrypt, blind_index
        obj = cls(
            subject_type=subject_type,
            name_enc=encrypt(name) if name else '',
            national_id_enc=encrypt(national_id) if national_id else '',
            contact_enc=encrypt(contact) if contact else '',
            name_blind_index=blind_index(name) if name else '',
            national_id_blind_index=blind_index(national_id) if national_id else '',
            created_by=created_by,
        )
        obj.save()
        return obj

    def __str__(self):
        return f"Subject #{self.pk} ({self.subject_type})"


class KeyRef(models.Model):
    """
    Envelope encryption metadata. The master key lives in HashiCorp Vault —
    never in this database. The wrapped_key here is the per-record data key,
    encrypted by the Vault master key.
    """
    subject = models.OneToOneField(SubjectIdentity, on_delete=models.CASCADE, related_name='key_ref')
    wrapped_key = models.TextField()
    key_version = models.CharField(max_length=50)
    kms_key_id = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(null=True, blank=True)


class ConsentRecord(models.Model):
    """
    Append-only consent log. Never update — only add new rows (e.g. for withdrawal).
    Donor consent is withdrawable but blood safety records stay regardless.
    """
    BASES = [
        ('consent', 'Explicit Consent'),
        ('vital_interest', 'Vital Interest'),
        ('healthcare_provision', 'Healthcare Provision'),
        ('legal_obligation', 'Legal Obligation'),
    ]

    subject = models.ForeignKey(SubjectIdentity, on_delete=models.PROTECT, related_name='consents')
    subject_type = models.CharField(max_length=10, choices=[('donor', 'Donor'), ('patient', 'Patient')])
    purpose = models.CharField(max_length=200)
    lawful_basis = models.CharField(max_length=30, choices=BASES)
    notice_version = models.CharField(max_length=20)
    captured_at = models.DateTimeField(auto_now_add=True)
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_note = models.TextField(blank=True)

    def __str__(self):
        status = "withdrawn" if self.withdrawn_at else "active"
        return f"{self.subject} / {self.purpose} ({status})"


class DSRRequest(models.Model):
    """Data Subject Rights requests (access, rectify, erase, etc.)"""
    TYPES = [
        ('access', 'Access'),
        ('rectify', 'Rectify'),
        ('erase', 'Erase'),
        ('restrict', 'Restrict'),
        ('portability', 'Portability'),
    ]
    STATUS = [
        ('received', 'Received'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('refused', 'Refused'),
    ]

    subject = models.ForeignKey(SubjectIdentity, on_delete=models.PROTECT, related_name='dsr_requests')
    request_type = models.CharField(max_length=15, choices=TYPES)
    status = models.CharField(max_length=15, choices=STATUS, default='received')
    requested_at = models.DateTimeField(auto_now_add=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.TextField(blank=True)
    refusal_reason = models.TextField(blank=True)

    def __str__(self):
        return f"DSR {self.get_request_type_display()} for subject #{self.subject_id} ({self.status})"
