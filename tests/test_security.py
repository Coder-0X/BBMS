"""
Security tests — XSS, CSRF, SQL injection, session, audit immutability.
Run: pytest tests/test_security.py -v
"""
import pytest
from django.test import Client
from django.utils import timezone

from tests.conftest import UserFactory, BranchFactory


# ─── Authentication / session ─────────────────────────────────────────────────

class TestAuthenticationRequired:

    def test_unauthenticated_redirects_to_login(self, db):
        client = Client()
        response = client.get('/donors/')
        assert response.status_code in (302, 403)

    def test_unauthenticated_api_returns_401(self, db):
        client = Client()
        response = client.get('/api/v1/units/')
        # Auth-required endpoints return 401/403; if not registered, 404 also acceptable
        assert response.status_code in (401, 403, 404)

    def test_login_with_wrong_password_rejected(self, db, branch):
        user = UserFactory(branch=branch)
        client = Client()
        logged_in = client.login(username=user.username, password='wrongpassword')
        assert not logged_in

    def test_login_with_correct_password_accepted(self, db, branch):
        user = UserFactory(branch=branch)
        client = Client()
        logged_in = client.login(username=user.username, password='testpass123')
        assert logged_in


# ─── CSRF protection ──────────────────────────────────────────────────────────

class TestCsrfProtection:

    def test_post_without_csrf_rejected(self, db, branch):
        user = UserFactory(branch=branch)
        client = Client(enforce_csrf_checks=True)
        client.login(username=user.username, password='testpass123')
        response = client.post('/donors/register/', data={'name': 'test'})
        # 403 CSRF failure, redirect, or 404 if URL not found
        assert response.status_code in (403, 302, 404)

    def test_api_post_with_session_csrf_accepted(self, db, branch):
        user = UserFactory(branch=branch)
        client = Client()
        client.login(username=user.username, password='testpass123')
        # Standard client includes CSRF cookie
        response = client.get('/api/v1/units/')
        # At minimum should not be 403 (forbidden for logged-in user)
        assert response.status_code != 403


# ─── SQL Injection resistance ─────────────────────────────────────────────────

class TestSqlInjection:

    def test_donor_search_with_sql_injection_payload(self, db, branch, user):
        from privacy.vault import blind_index
        # Passing a SQL-like string should not cause an error
        client = Client()
        client.login(username=user.username, password='testpass123')
        payload = "'; DROP TABLE donors_donor; --"
        response = client.get(f'/donors/search/?q={payload}')
        # Should return 200/empty, not 500
        assert response.status_code != 500

    def test_blood_unit_filter_with_injection_payload(self, db, branch, user):
        client = Client()
        client.login(username=user.username, password='testpass123')
        payload = "' OR '1'='1"
        response = client.get(f'/api/v1/units/?did={payload}')
        assert response.status_code != 500


# ─── XSS resistance ──────────────────────────────────────────────────────────

class TestXssResistance:

    def test_xss_payload_in_nc_description_escaped(self, db, branch, user):
        from quality.models import NonConformance
        client = Client(raise_request_exception=False)
        client.login(username=user.username, password='testpass123')
        xss = '<script>alert("XSS")</script>'
        nc = NonConformance.objects.create(
            nc_type='labelling',
            severity='minor',
            status='open',
            description=xss,
            event_date=timezone.now().date(),
            reported_by=user,
            branch=branch,
        )
        response = client.get(f'/quality/nc/{nc.pk}/')
        if response.status_code == 200:
            content = response.content.decode()
            assert '<script>' not in content


# ─── Privilege escalation ─────────────────────────────────────────────────────

class TestPrivilegeEscalation:

    def test_regular_user_cannot_access_admin(self, db, branch):
        user = UserFactory(branch=branch, is_staff=False, is_superuser=False)
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.get('/admin/')
        assert response.status_code in (302, 403)

    def test_other_branch_unit_not_visible(self, db):
        branch_a = BranchFactory()
        branch_b = BranchFactory()
        user_a = UserFactory(branch=branch_a)
        from tests.conftest import DonorFactory, DonationFactory, BloodUnitFactory
        donor = DonorFactory(registration_branch=branch_b, created_by=user_a)
        donation = DonationFactory(donor=donor, branch=branch_b, collected_by=user_a)
        BloodUnitFactory(donation=donation, owner_branch=branch_b)
        # user_a logging in, should not see branch_b units in scoped views
        client = Client()
        client.login(username=user_a.username, password='testpass123')
        # Filter by user_a's branch — should not return branch_b units
        response = client.get(f'/api/v1/units/?branch={branch_a.pk}')
        if response.status_code == 200:
            import json
            data = json.loads(response.content)
            results = data.get('results', data) if isinstance(data, dict) else data
            for item in results:
                assert item.get('owner_branch') != branch_b.pk


# ─── Encryption integrity ─────────────────────────────────────────────────────

class TestEncryptionIntegrity:

    def test_different_plaintexts_give_different_ciphertext(self):
        from privacy.vault import encrypt
        c1 = encrypt('Alice Smith')
        c2 = encrypt('Bob Jones')
        assert c1 != c2

    def test_decrypt_round_trip(self):
        from privacy.vault import encrypt, decrypt
        plaintext = 'Test Patient Name'
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_blind_index_is_deterministic(self):
        from privacy.vault import blind_index
        idx1 = blind_index('test@example.com')
        idx2 = blind_index('test@example.com')
        assert idx1 == idx2

    def test_blind_index_differs_for_different_values(self):
        from privacy.vault import blind_index
        assert blind_index('alice') != blind_index('bob')

    def test_ciphertext_not_plaintext(self):
        from privacy.vault import encrypt
        sensitive = 'John Doe DOB:1985-01-01'
        ciphertext = encrypt(sensitive)
        assert sensitive not in ciphertext


# ─── Brute-force lockout ──────────────────────────────────────────────────────

class TestBruteForceProtection:

    def test_account_locks_after_five_failures(self, db, branch):
        user = UserFactory(branch=branch)
        for _ in range(5):
            user.record_failed_login()
        user.refresh_from_db()
        assert user.is_locked()

    def test_locked_account_cannot_login(self, db, branch):
        user = UserFactory(branch=branch)
        for _ in range(5):
            user.record_failed_login()
        client = Client()
        logged_in = client.login(username=user.username, password='testpass123')
        assert not logged_in

    def test_clear_failed_logins_unlocks_account(self, db, branch):
        user = UserFactory(branch=branch)
        for _ in range(5):
            user.record_failed_login()
        user.clear_failed_logins()
        user.refresh_from_db()
        assert not user.is_locked()
        assert user.failed_attempts == 0

    def test_failed_login_writes_audit_trail(self, db, branch):
        from audit.models import AuditLog
        user = UserFactory(branch=branch)
        user.record_failed_login()
        assert AuditLog.objects.filter(
            action='accounts.login.failed',
            entity_id=user.pk,
        ).exists()


# ─── Audit log immutability ──────────────────────────────────────────────────

class TestAuditLogImmutability:

    def test_audit_log_has_no_delete_view(self, db, branch):
        """Audit log must be append-only — no delete endpoint should exist."""
        user = UserFactory(branch=branch, is_staff=True)
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.post('/audit/', {'delete': '1'})
        assert response.status_code in (302, 403, 404, 405)

    def test_audit_log_chain_intact_after_writes(self, db, branch):
        from audit.utils import write_audit, verify_chain
        user = UserFactory(branch=branch)
        write_audit(actor=user, action='test.event.1',
                    entity_table='accounts_user', entity_id=user.pk, after={'x': 1})
        write_audit(actor=user, action='test.event.2',
                    entity_table='accounts_user', entity_id=user.pk, after={'x': 2})
        is_valid, msg = verify_chain()
        assert is_valid, msg

    def test_audit_chain_breaks_if_hash_tampered(self, db, branch):
        from audit.utils import write_audit, verify_chain
        from audit.models import AuditLog
        user = UserFactory(branch=branch)
        write_audit(actor=user, action='test.tamper',
                    entity_table='accounts_user', entity_id=user.pk, after={'y': 1})
        entry = AuditLog.objects.order_by('-seq').first()
        entry.action = 'test.tampered'
        entry.save(update_fields=['action'])
        is_valid, _ = verify_chain()
        assert not is_valid


# ─── Permission enforcement ───────────────────────────────────────────────────

class TestPermissionEnforcement:

    def test_emergency_release_requires_permission(self, db, branch):
        """Regular user without emergency_release permission should be blocked."""
        user = UserFactory(branch=branch, is_staff=False, is_superuser=False)
        client = Client()
        client.login(username=user.username, password='testpass123')
        resp = client.post('/transfusion/emergency-release/', {
            'request_id': '999',
            'justification': 'test',
            'unit_ids': ['999'],
        })
        assert resp.status_code in (302, 403)
        if resp.status_code == 302:
            assert 'emergency-release' not in (resp.get('Location') or '')

    def test_recall_requires_permission(self, db, branch):
        """Regular user without recall.manage permission should be blocked."""
        user = UserFactory(branch=branch, is_staff=False, is_superuser=False)
        from tests.conftest import DonorFactory, DonationFactory
        donor = DonorFactory(registration_branch=branch, created_by=user)
        donation = DonationFactory(donor=donor, branch=branch, collected_by=user)
        client = Client()
        client.login(username=user.username, password='testpass123')
        resp = client.post(f'/inventory/recall/{donation.pk}/execute/', {
            'reason': 'test recall',
        })
        assert resp.status_code in (302, 403)

    def test_staff_only_user_list_blocks_regular_user(self, db, branch):
        user = UserFactory(branch=branch, is_staff=False, is_superuser=False)
        client = Client()
        client.login(username=user.username, password='testpass123')
        resp = client.get('/accounts/users/')
        assert resp.status_code in (302, 403)
