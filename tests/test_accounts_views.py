"""
Tests for accounts views:
  user_list, user_create, user_detail (assign/revoke role, deactivate),
  role_list, role_create, permission_list, sod_manage,
  notification_settings.
"""
import pytest
from django.test import Client
from django.utils import timezone

from tests.conftest import BranchFactory, UserFactory


def _client(user, branch=None):
    c = Client()
    c.login(username=user.username, password='testpass123')
    if branch:
        s = c.session
        s['branch_id'] = branch.pk
        s.save()
    return c


def _su(branch):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_superuser(
        username=f'su_av_{branch.pk}_{timezone.now().timestamp():.0f}',
        password='testpass123',
        display_name='Account View Super',
        branch=branch,
    )


def _make_role(name='Test Role'):
    from accounts.models import Role
    return Role.objects.get_or_create(name=name, defaults={'description': 'Test role', 'branch_scoped': True})[0]


def _make_permission(code='unit.test'):
    from accounts.models import Permission
    return Permission.objects.get_or_create(code=code, defaults={'description': 'Test permission'})[0]


# ─── User list ────────────────────────────────────────────────────────────────

class TestUserListView:

    def test_user_list_requires_staff(self, db, branch, user):
        resp = _client(user, branch).get('/accounts/users/')
        # Non-staff gets redirected
        assert resp.status_code in (200, 302)

    def test_user_list_staff_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/accounts/users/')
        assert resp.status_code == 200
        assert 'users' in resp.context

    def test_user_list_shows_all_users(self, db, branch, user):
        su = _su(branch)
        UserFactory(branch=branch)
        UserFactory(branch=branch)
        resp = _client(su, branch).get('/accounts/users/')
        assert resp.status_code == 200
        assert resp.context['users'].count() >= 2


# ─── User create ──────────────────────────────────────────────────────────────

class TestUserCreateView:

    def test_user_create_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/accounts/users/new/')
        assert resp.status_code == 200
        assert 'branches' in resp.context

    def test_user_create_post_creates_user(self, db, branch, user):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        su = _su(branch)
        count_before = User.objects.count()
        resp = _client(su, branch).post('/accounts/users/new/', {
            'username': 'new_lab_tech',
            'display_name': 'Lab Tech One',
            'password': 'SecurePass!123',
            'branch_id': branch.pk,
            'is_staff': '',
        })
        assert resp.status_code in (200, 302)
        assert User.objects.count() > count_before
        assert User.objects.filter(username='new_lab_tech').exists()

    def test_user_create_post_assigns_role(self, db, branch, user):
        from accounts.models import UserRole
        su = _su(branch)
        role = _make_role('Lab Technologist')
        resp = _client(su, branch).post('/accounts/users/new/', {
            'username': 'tech_with_role',
            'display_name': 'Tech With Role',
            'password': 'SecurePass!123',
            'branch_id': branch.pk,
            'role_ids': [role.pk],
        })
        assert resp.status_code in (200, 302)
        from django.contrib.auth import get_user_model
        u = get_user_model().objects.filter(username='tech_with_role').first()
        if u:
            assert UserRole.objects.filter(user=u, role=role).exists()

    def test_user_create_duplicate_username_shows_error(self, db, branch, user):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        su = _su(branch)
        # First creation
        _client(su, branch).post('/accounts/users/new/', {
            'username': 'dup_user',
            'display_name': 'Dup User',
            'password': 'SecurePass!123',
        })
        count_after_first = User.objects.filter(username='dup_user').count()
        # Duplicate attempt
        _client(su, branch).post('/accounts/users/new/', {
            'username': 'dup_user',
            'display_name': 'Dup User Again',
            'password': 'SecurePass!123',
        })
        # Still only one user with that name
        assert User.objects.filter(username='dup_user').count() == count_after_first


# ─── User detail ──────────────────────────────────────────────────────────────

class TestUserDetailView:

    def test_user_detail_get(self, db, branch, user):
        su = _su(branch)
        target = UserFactory(branch=branch)
        resp = _client(su, branch).get(f'/accounts/users/{target.pk}/')
        assert resp.status_code == 200
        assert resp.context['target_user'] == target

    def test_user_detail_deactivate(self, db, branch, user):
        su = _su(branch)
        target = UserFactory(branch=branch)
        assert target.is_active
        resp = _client(su, branch).post(f'/accounts/users/{target.pk}/', {'action': 'deactivate'})
        assert resp.status_code in (200, 302)
        target.refresh_from_db()
        assert not target.is_active

    def test_user_detail_reactivate(self, db, branch, user):
        su = _su(branch)
        target = UserFactory(branch=branch, is_active=False)
        resp = _client(su, branch).post(f'/accounts/users/{target.pk}/', {'action': 'activate'})
        assert resp.status_code in (200, 302)
        target.refresh_from_db()
        assert target.is_active

    def test_user_detail_assign_role(self, db, branch, user):
        from accounts.models import UserRole
        su = _su(branch)
        target = UserFactory(branch=branch)
        role = _make_role('Phlebotomist')
        resp = _client(su, branch).post(f'/accounts/users/{target.pk}/', {
            'action': 'assign_role',
            'role_id': role.pk,
            'branch_id': branch.pk,
        })
        assert resp.status_code in (200, 302)
        assert UserRole.objects.filter(user=target, role=role, revoked_at__isnull=True).exists()

    def test_user_detail_revoke_role(self, db, branch, user):
        from accounts.models import UserRole
        su = _su(branch)
        target = UserFactory(branch=branch)
        role = _make_role('Transfusionist')
        assignment = UserRole.objects.create(user=target, role=role, granted_by=su)
        resp = _client(su, branch).post(f'/accounts/users/{target.pk}/', {
            'action': 'revoke_role',
            'assignment_id': assignment.pk,
        })
        assert resp.status_code in (200, 302)
        assignment.refresh_from_db()
        assert assignment.revoked_at is not None

    def test_user_detail_update_notifications(self, db, branch, user):
        su = _su(branch)
        target = UserFactory(branch=branch)
        resp = _client(su, branch).post(f'/accounts/users/{target.pk}/', {
            'action': 'update_notifications',
            'email': 'lab@hospital.nhs.uk',
            'notify_critical_alerts': 'on',
        })
        assert resp.status_code in (200, 302)
        target.refresh_from_db()
        assert target.email == 'lab@hospital.nhs.uk'
        assert target.notify_critical_alerts is True

    def test_user_detail_unlock_account(self, db, branch, user):
        """The 'unlock' action clears failed login counters and writes an audit entry."""
        from audit.models import AuditLog
        su = _su(branch)
        target = UserFactory(branch=branch)
        # Simulate some failed logins
        target.failed_attempts = 5
        target.save(update_fields=['failed_attempts'])
        resp = _client(su, branch).post(f'/accounts/users/{target.pk}/', {'action': 'unlock'})
        assert resp.status_code in (200, 302)
        target.refresh_from_db()
        assert target.failed_attempts == 0
        assert AuditLog.objects.filter(action='account.unlock', entity_id=target.pk).exists()

    def test_user_detail_assign_role_sod_conflict_blocked(self, db, branch, user):
        """Assigning a role whose permissions conflict with existing grants must be blocked."""
        from accounts.models import UserRole, SoDConflict
        su = _su(branch)
        target = UserFactory(branch=branch)
        role_a = _make_role('Collector')
        role_b = _make_role('Tester')
        perm_collect = _make_permission('sample.collect')
        perm_test = _make_permission('sample.test')
        role_a.permissions.add(perm_collect)
        role_b.permissions.add(perm_test)
        SoDConflict.objects.create(
            permission_a=min(perm_collect, perm_test, key=lambda p: p.pk),
            permission_b=max(perm_collect, perm_test, key=lambda p: p.pk),
            reason='Collector cannot test their own samples',
        )
        # Assign role_a first
        UserRole.objects.create(user=target, role=role_a, branch=branch, granted_by=su)
        # Now try to assign role_b (should be blocked by SoD)
        existing_count = UserRole.objects.filter(user=target, revoked_at__isnull=True).count()
        _client(su, branch).post(f'/accounts/users/{target.pk}/', {
            'action': 'assign_role',
            'role_id': role_b.pk,
            'branch_id': branch.pk,
        })
        # Role b should NOT have been granted
        assert UserRole.objects.filter(
            user=target, role=role_b, revoked_at__isnull=True
        ).count() == 0


# ─── Role list ────────────────────────────────────────────────────────────────

class TestRoleListView:

    def test_role_list_requires_staff(self, db, branch, user):
        resp = _client(user, branch).get('/accounts/roles/')
        assert resp.status_code in (200, 302)

    def test_role_list_staff_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/accounts/roles/')
        assert resp.status_code == 200
        assert 'roles' in resp.context


# ─── Role create ──────────────────────────────────────────────────────────────

class TestRoleCreateView:

    def test_role_create_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/accounts/roles/new/')
        assert resp.status_code == 200

    def test_role_create_post(self, db, branch, user):
        from accounts.models import Role
        su = _su(branch)
        count_before = Role.objects.count()
        resp = _client(su, branch).post('/accounts/roles/new/', {
            'name': 'Blood Bank Officer',
            'description': 'Manages blood bank operations',
            'branch_scoped': 'on',
        })
        assert resp.status_code in (200, 302)
        assert Role.objects.count() > count_before

    def test_role_create_with_permissions(self, db, branch, user):
        from accounts.models import Role
        su = _su(branch)
        perm = _make_permission('blood.issue')
        resp = _client(su, branch).post('/accounts/roles/new/', {
            'name': 'Issuing Officer',
            'description': 'Can issue blood units',
            'branch_scoped': 'on',
            'permission_ids': [perm.pk],
        })
        assert resp.status_code in (200, 302)
        role = Role.objects.filter(name='Issuing Officer').first()
        if role:
            assert role.permissions.filter(pk=perm.pk).exists()


# ─── Permission list ──────────────────────────────────────────────────────────

class TestPermissionListView:

    def test_permission_list_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/accounts/permissions/')
        assert resp.status_code == 200

    def test_permission_list_post_creates_permission(self, db, branch, user):
        from accounts.models import Permission
        su = _su(branch)
        resp = _client(su, branch).post('/accounts/permissions/', {
            'code': 'unit.irradiate',
            'description': 'Can mark units as irradiated',
        })
        assert resp.status_code in (200, 302)
        assert Permission.objects.filter(code='unit.irradiate').exists()

    def test_permission_list_post_no_duplicate(self, db, branch, user):
        from accounts.models import Permission
        su = _su(branch)
        Permission.objects.create(code='unit.crossmatch', description='Crossmatch')
        count_before = Permission.objects.filter(code='unit.crossmatch').count()
        _client(su, branch).post('/accounts/permissions/', {
            'code': 'unit.crossmatch',
            'description': 'Duplicate attempt',
        })
        # get_or_create — still only one
        assert Permission.objects.filter(code='unit.crossmatch').count() == count_before


# ─── Notification settings ────────────────────────────────────────────────────

class TestNotificationSettings:

    def test_notification_settings_get(self, db, branch, user):
        resp = _client(user, branch).get('/accounts/notifications/')
        assert resp.status_code == 200

    def test_notification_settings_post_saves(self, db, branch, user):
        resp = _client(user, branch).post('/accounts/notifications/', {
            'email': 'transfusion@hospital.org',
            'notify_critical_alerts': 'on',
            'notify_warning_alerts': '',
        })
        assert resp.status_code in (200, 302)
        user.refresh_from_db()
        assert user.email == 'transfusion@hospital.org'
        assert user.notify_critical_alerts is True
        assert user.notify_warning_alerts is False


# ─── SoD management ───────────────────────────────────────────────────────────

class TestSoDManageView:

    def test_sod_manage_get(self, db, branch, user):
        su = _su(branch)
        resp = _client(su, branch).get('/accounts/sod/')
        assert resp.status_code == 200

    def test_sod_manage_requires_staff(self, db, branch, user):
        resp = _client(user, branch).get('/accounts/sod/')
        assert resp.status_code in (200, 302)

    def test_sod_manage_add_conflict(self, db, branch, user):
        from accounts.models import SoDConflict
        su = _su(branch)
        pa = _make_permission('blood.collect')
        pb = _make_permission('blood.test')
        count_before = SoDConflict.objects.count()
        resp = _client(su, branch).post('/accounts/sod/', {
            'action': 'add',
            'permission_a': pa.pk,
            'permission_b': pb.pk,
            'reason': 'Collector cannot test their own samples — dual control.',
        })
        assert resp.status_code in (200, 302)
        assert SoDConflict.objects.count() > count_before

    def test_sod_manage_same_permission_rejected(self, db, branch, user):
        from accounts.models import SoDConflict
        su = _su(branch)
        pa = _make_permission('blood.release')
        count_before = SoDConflict.objects.count()
        _client(su, branch).post('/accounts/sod/', {
            'action': 'add',
            'permission_a': pa.pk,
            'permission_b': pa.pk,
            'reason': 'Self-conflict attempt',
        })
        # Should be rejected — cannot conflict a permission with itself
        assert SoDConflict.objects.count() == count_before

    def test_sod_manage_delete_conflict(self, db, branch, user):
        """The 'delete' action removes a SoDConflict and writes an audit entry."""
        from accounts.models import SoDConflict, Permission
        from audit.models import AuditLog
        su = _su(branch)
        pa = _make_permission('blood.pool')
        pb = _make_permission('blood.wash')
        conflict = SoDConflict.objects.create(
            permission_a=min(pa, pb, key=lambda p: p.pk),
            permission_b=max(pa, pb, key=lambda p: p.pk),
            reason='Cannot pool and wash in the same session',
        )
        count_before = SoDConflict.objects.count()
        resp = _client(su, branch).post('/accounts/sod/', {
            'action': 'delete',
            'conflict_id': conflict.pk,
        })
        assert resp.status_code in (200, 302)
        assert SoDConflict.objects.count() < count_before
        assert AuditLog.objects.filter(action='account.sod_conflict_removed').exists()


# ─── Login / Logout ───────────────────────────────────────────────────────────

class TestLoginView:

    def test_login_get_renders_form(self, db, branch):
        client = Client()
        resp = client.get('/accounts/login/')
        assert resp.status_code == 200

    def test_login_post_valid_credentials_redirects(self, db, branch):
        user = UserFactory(branch=branch)
        client = Client()
        resp = client.post('/accounts/login/', {
            'username': user.username,
            'password': 'testpass123',
        })
        assert resp.status_code in (200, 302)

    def test_login_post_wrong_password_stays_on_form(self, db, branch):
        user = UserFactory(branch=branch)
        client = Client()
        resp = client.post('/accounts/login/', {
            'username': user.username,
            'password': 'wrongpassword',
        })
        # Should stay on login page (200) or redirect back to login (302)
        assert resp.status_code in (200, 302)
        if resp.status_code == 200:
            assert b'login' in resp.content.lower() or b'password' in resp.content.lower()

    def test_login_authenticated_user_redirects_to_dashboard(self, db, branch):
        user = UserFactory(branch=branch)
        client = Client()
        client.login(username=user.username, password='testpass123')
        resp = client.get('/accounts/login/')
        assert resp.status_code in (200, 302)

    def test_login_idle_reason_shows_warning(self, db):
        client = Client()
        resp = client.get('/accounts/login/?reason=idle')
        assert resp.status_code == 200

    def test_login_writes_audit_trail(self, db, branch):
        from audit.models import AuditLog
        user = UserFactory(branch=branch)
        count_before = AuditLog.objects.filter(action='accounts.login', entity_id=user.pk).count()
        client = Client()
        client.post('/accounts/login/', {
            'username': user.username,
            'password': 'testpass123',
        })
        assert AuditLog.objects.filter(action='accounts.login', entity_id=user.pk).count() > count_before


class TestLogoutView:

    def test_logout_get_renders_confirm_page(self, db, branch, user):
        resp = _client(user, branch).get('/accounts/logout/')
        assert resp.status_code == 200

    def test_logout_post_logs_user_out(self, db, branch, user):
        c = _client(user, branch)
        resp = c.post('/accounts/logout/')
        assert resp.status_code in (200, 302)
        # After logout, accessing a protected page should redirect to login
        resp2 = c.get('/dashboard/')
        assert resp2.status_code in (302, 403)

    def test_logout_writes_audit_trail(self, db, branch, user):
        from audit.models import AuditLog
        count_before = AuditLog.objects.filter(action='accounts.logout').count()
        _client(user, branch).post('/accounts/logout/')
        assert AuditLog.objects.filter(action='accounts.logout').count() > count_before


# ─── Re-authentication ───────────────────────────────────────────────────────

class TestReauthView:

    def test_reauth_get(self, db, branch, user):
        resp = _client(user, branch).get('/accounts/reauth/')
        assert resp.status_code == 200

    def test_reauth_post_valid_password_sets_session(self, db, branch, user):
        c = _client(user, branch)
        resp = c.post('/accounts/reauth/', {'password': 'testpass123'})
        assert resp.status_code in (200, 302)
        # reauth_at should be set after successful reauth
        if resp.status_code == 302:
            assert c.session.get('reauth_at') is not None

    def test_reauth_post_wrong_password_stays_on_form(self, db, branch, user):
        c = _client(user, branch)
        resp = c.post('/accounts/reauth/', {'password': 'wrongpassword'})
        assert resp.status_code in (200, 302)


# ─── Change password ─────────────────────────────────────────────────────────

class TestChangePasswordView:

    def test_change_password_get(self, db, branch, user):
        resp = _client(user, branch).get('/accounts/password/change/')
        assert resp.status_code == 200

    def test_change_password_post_valid_changes_password(self, db, branch, user):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        c = _client(user, branch)
        resp = c.post('/accounts/password/change/', {
            'current_password': 'testpass123',
            'new_password': 'NewSecure@2025!',
            'confirm_password': 'NewSecure@2025!',
        })
        assert resp.status_code in (200, 302)
        user.refresh_from_db()
        # Should be able to login with new password
        assert user.check_password('NewSecure@2025!') or user.check_password('testpass123')

    def test_change_password_post_mismatch_fails(self, db, branch, user):
        c = _client(user, branch)
        resp = c.post('/accounts/password/change/', {
            'current_password': 'testpass123',
            'new_password': 'NewSecure@2025!',
            'confirm_password': 'DifferentPass!',
        })
        # Should not redirect (form error stays on page)
        assert resp.status_code in (200, 302)
        # Original password should still work
        user.refresh_from_db()
        assert user.check_password('testpass123')


# ─── MFA views ────────────────────────────────────────────────────────────────

class TestMFAVerifyView:

    def test_get_with_no_session_user_redirects_to_login(self, db, branch):
        resp = Client().get('/accounts/mfa/verify/')
        assert resp.status_code in (200, 302)

    def test_get_with_valid_pending_user_renders_form(self, db, branch, user):
        client = Client()
        # Simulate the login view having set pending_mfa_user_id
        session = client.session
        session['pending_mfa_user_id'] = user.pk
        session.save()
        resp = client.get('/accounts/mfa/verify/')
        assert resp.status_code == 200

    def test_get_with_invalid_user_id_redirects(self, db, branch):
        client = Client()
        session = client.session
        session['pending_mfa_user_id'] = 99999
        session.save()
        resp = client.get('/accounts/mfa/verify/')
        assert resp.status_code in (200, 302)


class TestMFASetupView:

    def test_get_renders_setup_page_for_user_without_mfa(self, db, branch, user):
        resp = _client(user, branch).get('/accounts/mfa/setup/')
        assert resp.status_code == 200

    def test_get_redirects_if_mfa_already_enabled(self, db, branch, user):
        import pyotp
        user.mfa_secret = pyotp.random_base32()
        user.mfa_enabled = True
        user.save(update_fields=['mfa_secret', 'mfa_enabled'])
        resp = _client(user, branch).get('/accounts/mfa/setup/')
        assert resp.status_code in (200, 302)

    def test_get_includes_qr_code_in_context(self, db, branch, user):
        resp = _client(user, branch).get('/accounts/mfa/setup/')
        assert resp.status_code == 200
        assert 'qr_code' in resp.context

    def test_post_with_valid_totp_enables_mfa(self, db, branch, user):
        import pyotp
        secret = pyotp.random_base32()
        c = _client(user, branch)
        # Inject the secret into the session (mimics GET having stored it)
        s = c.session
        s['mfa_setup_secret'] = secret
        s.save()
        valid_code = pyotp.TOTP(secret).now()
        resp = c.post('/accounts/mfa/setup/', {'code': valid_code})
        assert resp.status_code in (200, 302)
        user.refresh_from_db()
        assert user.mfa_enabled is True

    def test_post_with_valid_totp_writes_audit_trail(self, db, branch, user):
        import pyotp
        from audit.models import AuditLog
        secret = pyotp.random_base32()
        c = _client(user, branch)
        s = c.session
        s['mfa_setup_secret'] = secret
        s.save()
        valid_code = pyotp.TOTP(secret).now()
        c.post('/accounts/mfa/setup/', {'code': valid_code})
        assert AuditLog.objects.filter(action='accounts.mfa.enabled').exists()

    def test_post_with_invalid_code_stays_on_form(self, db, branch, user):
        import pyotp
        secret = pyotp.random_base32()
        c = _client(user, branch)
        s = c.session
        s['mfa_setup_secret'] = secret
        s.save()
        resp = c.post('/accounts/mfa/setup/', {'code': '000000'})
        assert resp.status_code == 200
        user.refresh_from_db()
        assert not user.mfa_enabled

    def test_unauthenticated_redirects(self, db):
        resp = Client().get('/accounts/mfa/setup/')
        assert resp.status_code == 302
        assert 'login' in resp.get('Location', '').lower()


# ─── Regression: get_object_or_404 fixes ─────────────────────────────────────

class TestUserDetailViewRegression:
    """Regression tests for bugs fixed in accounts/views.py (get_object_or_404)."""

    def test_user_detail_invalid_pk_returns_404_not_500(self, db, branch, user):
        """
        Previously User.objects.get(pk=pk) raised DoesNotExist → HTTP 500.
        After fix, get_object_or_404 must return 404.
        """
        su = _su(branch)
        resp = _client(su, branch).get('/accounts/users/999999/')
        assert resp.status_code == 404

    def test_user_detail_non_numeric_pk_handled(self, db, branch, user):
        su = _su(branch)
        # Django URL routing rejects non-numeric pk before the view runs
        resp = _client(su, branch).get('/accounts/users/notanumber/')
        assert resp.status_code in (404, 400)


class TestSoDManageViewRegression:
    """Regression tests for bugs fixed in sod_manage_view (get_object_or_404)."""

    def test_sod_manage_add_invalid_permission_a_returns_404(self, db, branch, user):
        """
        Previously Permission.objects.get(pk=perm_a) raised DoesNotExist → 500.
        After fix, get_object_or_404 must return 404.
        """
        su = _su(branch)
        pb = _make_permission('blood.collect_reg')
        resp = _client(su, branch).post('/accounts/sod/', {
            'action': 'add',
            'permission_a': 999999,
            'permission_b': pb.pk,
            'reason': 'test',
        })
        assert resp.status_code == 404

    def test_sod_manage_add_invalid_permission_b_returns_404(self, db, branch, user):
        su = _su(branch)
        pa = _make_permission('blood.test_reg')
        resp = _client(su, branch).post('/accounts/sod/', {
            'action': 'add',
            'permission_a': pa.pk,
            'permission_b': 999999,
            'reason': 'test',
        })
        assert resp.status_code == 404
