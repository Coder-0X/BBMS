from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, username, password, branch=None, **extra):
        if not username:
            raise ValueError("Username is required")
        user = self.model(username=username, branch=branch, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        return self.create_user(username, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=200)
    branch = models.ForeignKey(
        'core.Branch', null=True, blank=True,
        on_delete=models.PROTECT, related_name='users',
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )

    # Contact / notification
    email = models.EmailField(blank=True, help_text='Used for critical alert notifications.')
    notify_critical_alerts = models.BooleanField(
        default=False,
        help_text='Receive email when a critical alert is raised at your branch.',
    )
    notify_warning_alerts = models.BooleanField(
        default=False,
        help_text='Receive email when a warning alert is raised at your branch.',
    )

    # MFA
    mfa_secret = models.CharField(max_length=64, blank=True)
    mfa_enabled = models.BooleanField(default=False)
    # Stored as a JSON list of hashed backup codes
    mfa_recovery_codes = models.JSONField(default=list, blank=True)

    # Brute-force protection
    failed_attempts = models.SmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['display_name']

    objects = UserManager()

    def is_locked(self) -> bool:
        if self.locked_until and self.locked_until > timezone.now():
            return True
        return False

    def record_failed_login(self):
        self.failed_attempts += 1
        if self.failed_attempts >= 5:
            from datetime import timedelta
            # Exponential backoff: 15 min, 30 min, 60 min, ...
            minutes = 15 * (2 ** (self.failed_attempts - 5))
            self.locked_until = timezone.now() + timedelta(minutes=min(minutes, 1440))
        self.save(update_fields=['failed_attempts', 'locked_until'])
        from audit.utils import write_audit
        write_audit(
            actor=self,
            action='accounts.login.failed',
            entity_table='accounts_user',
            entity_id=self.pk,
            after={
                'failed_attempts': self.failed_attempts,
                'locked': self.locked_until is not None,
            },
        )

    def clear_failed_logins(self):
        self.failed_attempts = 0
        self.locked_until = None
        self.save(update_fields=['failed_attempts', 'locked_until'])

    def __str__(self):
        return self.display_name or self.username


class Permission(models.Model):
    """
    Fine-grained permission codes like 'unit.release', 'donor.read_pii'.
    These are our own codes, separate from Django's built-in permissions.
    """
    code = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=500)

    def __str__(self):
        return self.code


class Role(models.Model):
    name = models.CharField(max_length=100)
    # If True, a user's grant of this role is scoped to one branch
    branch_scoped = models.BooleanField(default=True)
    description = models.CharField(max_length=500, blank=True)
    permissions = models.ManyToManyField(Permission, blank=True, related_name='roles')

    def __str__(self):
        return self.name


class UserRole(models.Model):
    """Grants a role to a user, optionally at a specific branch."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    # Null means the role applies at all branches
    branch = models.ForeignKey(
        'core.Branch', null=True, blank=True,
        on_delete=models.CASCADE, related_name='+',
    )
    granted_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='+')
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('user', 'role', 'branch')]

    def is_active(self) -> bool:
        return self.revoked_at is None

    def __str__(self):
        scope = f" @ {self.branch}" if self.branch else " (all branches)"
        return f"{self.user} → {self.role}{scope}"


class SoDConflict(models.Model):
    """
    Two permissions that can never be held by the same user at the same time.
    E.g. 'test.perform' and 'unit.release' conflict — the tester can't also release.
    """
    permission_a = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='+')
    permission_b = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='+')
    reason = models.CharField(max_length=500)

    class Meta:
        unique_together = [('permission_a', 'permission_b')]

    def __str__(self):
        return f"{self.permission_a.code} ✕ {self.permission_b.code}"


class BreakGlassSession(models.Model):
    """Emergency elevated access, fully audited."""
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='break_glass_sessions')
    reason_code = models.CharField(max_length=50)
    justification = models.TextField()
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    alert_sent_to = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def is_active(self) -> bool:
        return timezone.now() < self.expires_at

    def __str__(self):
        return f"{self.user} break-glass @ {self.granted_at:%Y-%m-%d %H:%M}"
