from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from .forms import LoginForm, MFAVerifyForm, MFASetupForm, ReauthForm, PasswordChangeForm
from . import mfa as mfa_utils


def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    reason = request.GET.get('reason')
    if reason == 'idle':
        messages.warning(request, "You were logged out due to inactivity.")
    elif reason == 'expired':
        messages.warning(request, "Your session has expired. Please log in again.")

    form = LoginForm(request.POST or None, request=request)

    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        user.clear_failed_logins()

        if user.mfa_enabled:
            # Don't log in yet — hold the user id in session and send to MFA step
            request.session['pending_mfa_user_id'] = user.pk
            return redirect('accounts:mfa_verify')

        login(request, user)
        request.session['session_start'] = timezone.now().isoformat()
        from audit.utils import write_audit
        write_audit(
            actor=user,
            action='accounts.login',
            entity_table='accounts_user',
            entity_id=user.pk,
            after={'method': 'password'},
        )
        return redirect(request.GET.get('next', 'core:dashboard'))

    return render(request, 'accounts/login.html', {'form': form})


def mfa_verify_view(request):
    user_id = request.session.get('pending_mfa_user_id')
    if not user_id:
        return redirect('accounts:login')

    from .models import User
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return redirect('accounts:login')

    form = MFAVerifyForm(request.POST or None, secret=user.mfa_secret)

    if request.method == 'POST' and form.is_valid():
        del request.session['pending_mfa_user_id']
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        request.session['session_start'] = timezone.now().isoformat()
        from audit.utils import write_audit
        write_audit(
            actor=user,
            action='accounts.login',
            entity_table='accounts_user',
            entity_id=user.pk,
            after={'method': 'password+totp'},
        )
        return redirect(request.GET.get('next', 'core:dashboard'))

    return render(request, 'accounts/mfa_verify.html', {'form': form})


@login_required
def mfa_setup_view(request):
    user = request.user

    if user.mfa_enabled:
        messages.info(request, "MFA is already enabled on your account.")
        return redirect('core:dashboard')

    # Generate a new secret and store it in session until confirmed
    if 'mfa_setup_secret' not in request.session:
        request.session['mfa_setup_secret'] = mfa_utils.generate_mfa_secret()

    secret = request.session['mfa_setup_secret']
    qr_code = mfa_utils.get_qr_code_base64(secret, user.username)
    form = MFASetupForm(request.POST or None, secret=secret)

    if request.method == 'POST' and form.is_valid():
        plain_codes, hashed_codes = mfa_utils.generate_recovery_codes()
        user.mfa_secret = secret
        user.mfa_enabled = True
        user.mfa_recovery_codes = hashed_codes
        user.save(update_fields=['mfa_secret', 'mfa_enabled', 'mfa_recovery_codes'])
        del request.session['mfa_setup_secret']
        from audit.utils import write_audit
        write_audit(
            actor=user,
            action='accounts.mfa.enabled',
            entity_table='accounts_user',
            entity_id=user.pk,
            after={'mfa_enabled': True},
            action_meaning='User enabled TOTP multi-factor authentication',
        )
        return render(request, 'accounts/mfa_recovery_codes.html', {'codes': plain_codes})

    return render(request, 'accounts/mfa_setup.html', {
        'form': form,
        'qr_code': qr_code,
        'secret': secret,  # shown as manual entry fallback
    })


@login_required
def logout_view(request):
    if request.method == 'POST':
        from audit.utils import write_audit
        write_audit(
            actor=request.user,
            action='accounts.logout',
            entity_table='accounts_user',
            entity_id=request.user.pk,
            after={},
        )
        logout(request)
        return redirect('accounts:login')
    return render(request, 'accounts/logout_confirm.html')


@login_required
def reauth_view(request):
    """
    Re-authentication gate before signing a record.
    On success, stamps request.session['reauth_at'] and redirects to ?next=.
    """
    form = ReauthForm(request.POST or None, user=request.user)

    if request.method == 'POST' and form.is_valid():
        request.session['reauth_at'] = timezone.now().isoformat()
        return redirect(request.GET.get('next', 'core:dashboard'))

    return render(request, 'accounts/reauth.html', {'form': form})


@login_required
def change_password_view(request):
    form = PasswordChangeForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        request.user.set_password(form.cleaned_data['new_password'])
        request.user.save(update_fields=['password'])
        from audit.utils import write_audit
        write_audit(
            actor=request.user,
            action='account.password_change',
            entity_table='accounts_user',
            entity_id=request.user.pk,
        )
        messages.success(request, "Password changed successfully. Please log in again.")
        from django.contrib.auth import logout
        logout(request)
        return redirect('accounts:login')
    return render(request, 'accounts/change_password.html', {'form': form})


@login_required
def user_list_view(request):
    if not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')
    from .models import User
    users = User.objects.select_related('branch').order_by('username')
    return render(request, 'accounts/user_list.html', {'users': users})


@login_required
def user_create_view(request):
    if not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')
    from .models import User, Role, UserRole
    from core.models import Branch

    if request.method == 'POST':
        username = request.POST['username'].strip()
        display_name = request.POST['display_name'].strip()
        password = request.POST['password']
        branch_id = request.POST.get('branch_id') or None
        is_staff = request.POST.get('is_staff') == 'on'

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken.")
        else:
            new_user = User.objects.create_user(
                username=username,
                password=password,
                display_name=display_name,
                branch_id=branch_id,
                is_staff=is_staff,
                created_by=request.user,
            )
            role_ids = request.POST.getlist('role_ids')
            for role_id in role_ids:
                UserRole.objects.create(
                    user=new_user,
                    role_id=role_id,
                    branch_id=branch_id,
                    granted_by=request.user,
                )
            from audit.utils import write_audit
            write_audit(
                actor=request.user,
                action='account.user_create',
                entity_table='accounts_user',
                entity_id=new_user.pk,
                after={'username': username, 'display_name': display_name},
            )
            messages.success(request, f"User '{username}' created.")
            return redirect('accounts:user_list')

    branches = Branch.objects.filter(active=True).order_by('name')
    roles = Role.objects.all().order_by('name')
    return render(request, 'accounts/user_form.html', {'branches': branches, 'roles': roles})


@login_required
def user_detail_view(request, pk):
    if not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')
    from .models import User, Role, UserRole
    from core.models import Branch
    target_user = get_object_or_404(User, pk=pk)
    user_roles = target_user.user_roles.select_related('role', 'branch').filter(revoked_at__isnull=True)
    all_roles = Role.objects.all().order_by('name')
    branches = Branch.objects.filter(active=True).order_by('name')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'assign_role':
            role_id = request.POST['role_id']
            branch_id = request.POST.get('branch_id') or None
            from core.models import Branch as CoreBranch
            branch_obj = get_object_or_404(CoreBranch, pk=branch_id) if branch_id else None

            # SoD check — block if any permission on this role conflicts with existing user perms
            from .models import Role as RoleModel
            from accounts.permissions import check_sod_violation
            role = get_object_or_404(RoleModel, pk=role_id)
            conflicts_found = []
            for perm in role.permissions.all():
                conflict_reason = check_sod_violation(target_user, perm.code, branch_obj)
                if conflict_reason:
                    conflicts_found.append(f"'{perm.code}': {conflict_reason}")

            if conflicts_found:
                messages.error(request, "Role assignment blocked — SoD conflict: " + "; ".join(conflicts_found))
            else:
                UserRole.objects.get_or_create(
                    user=target_user, role_id=role_id, branch_id=branch_id,
                    defaults={'granted_by': request.user},
                )
                from accounts.permissions import invalidate_permission_cache
                invalidate_permission_cache(target_user, branch_obj)
                from audit.utils import write_audit
                write_audit(
                    actor=request.user,
                    action='account.role_assigned',
                    entity_table='accounts_user',
                    entity_id=target_user.pk,
                    after={'role': role.name, 'branch_id': branch_id, 'target_user': target_user.username},
                )
                messages.success(request, f"Role '{role.name}' assigned.")
        elif action == 'revoke_role':
            role_assignment_id = request.POST['assignment_id']
            assignment = UserRole.objects.filter(pk=role_assignment_id, user=target_user).first()
            role_name = assignment.role.name if assignment else '?'
            UserRole.objects.filter(pk=role_assignment_id, user=target_user).update(
                revoked_at=timezone.now()
            )
            from audit.utils import write_audit
            write_audit(
                actor=request.user,
                action='account.role_revoked',
                entity_table='accounts_user',
                entity_id=target_user.pk,
                after={'role': role_name, 'target_user': target_user.username},
            )
            messages.success(request, "Role revoked.")
        elif action == 'deactivate':
            target_user.is_active = False
            target_user.save(update_fields=['is_active'])
            from audit.utils import write_audit
            write_audit(
                actor=request.user,
                action='account.deactivate',
                entity_table='accounts_user',
                entity_id=target_user.pk,
                before={'is_active': True},
                after={'is_active': False, 'target_user': target_user.username},
            )
            messages.warning(request, f"User '{target_user.username}' deactivated.")
        elif action == 'activate':
            target_user.is_active = True
            target_user.save(update_fields=['is_active'])
            from audit.utils import write_audit
            write_audit(
                actor=request.user,
                action='account.activate',
                entity_table='accounts_user',
                entity_id=target_user.pk,
                before={'is_active': False},
                after={'is_active': True, 'target_user': target_user.username},
            )
            messages.success(request, f"User '{target_user.username}' activated.")
        elif action == 'unlock':
            target_user.clear_failed_logins()
            from audit.utils import write_audit
            write_audit(
                actor=request.user,
                action='account.unlock',
                entity_table='accounts_user',
                entity_id=target_user.pk,
                after={'target_user': target_user.username},
            )
            messages.success(request, "Account unlocked.")
        elif action == 'update_notifications':
            target_user.email = request.POST.get('email', '').strip()
            target_user.notify_critical_alerts = request.POST.get('notify_critical_alerts') == 'on'
            target_user.notify_warning_alerts = request.POST.get('notify_warning_alerts') == 'on'
            target_user.save(update_fields=['email', 'notify_critical_alerts', 'notify_warning_alerts'])
            messages.success(request, "Notification preferences updated.")
        return redirect('accounts:user_detail', pk=pk)

    return render(request, 'accounts/user_detail.html', {
        'target_user': target_user,
        'user_roles': user_roles,
        'all_roles': all_roles,
        'branches': branches,
    })


@login_required
def role_list_view(request):
    if not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')
    from .models import Role, SoDConflict
    roles = Role.objects.prefetch_related('permissions').order_by('name')
    conflicts = SoDConflict.objects.select_related('permission_a', 'permission_b').all()
    return render(request, 'accounts/role_list.html', {
        'roles': roles,
        'conflicts': conflicts,
    })


@login_required
def role_create_view(request):
    if not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')
    from .models import Role, Permission

    if request.method == 'POST':
        name = request.POST['name'].strip()
        description = request.POST.get('description', '')
        branch_scoped = request.POST.get('branch_scoped') == 'on'
        role = Role.objects.create(name=name, description=description, branch_scoped=branch_scoped)
        perm_ids = request.POST.getlist('permission_ids')
        if perm_ids:
            role.permissions.set(Permission.objects.filter(pk__in=perm_ids))
        from audit.utils import write_audit
        write_audit(
            actor=request.user,
            action='account.role_create',
            entity_table='accounts_role',
            entity_id=role.pk,
            after={'name': name, 'permissions': perm_ids},
        )
        messages.success(request, f"Role '{name}' created.")
        return redirect('accounts:role_list')

    permissions = Permission.objects.all().order_by('code')
    return render(request, 'accounts/role_form.html', {'permissions': permissions, 'role': None})


@login_required
def permission_list_view(request):
    if not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')
    from .models import Permission

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        if not code:
            messages.error(request, "Permission code is required.")
            return redirect('accounts:permission_list')
        description = request.POST.get('description', '')
        _perm, created = Permission.objects.get_or_create(code=code, defaults={'description': description})
        if created:
            from audit.utils import write_audit
            write_audit(
                actor=request.user,
                action='account.permission_created',
                entity_table='accounts_permission',
                entity_id=_perm.pk,
                after={'code': code, 'description': description},
            )
        messages.success(request, f"Permission '{code}' {'created' if created else 'already exists'}.")
        return redirect('accounts:permission_list')

    permissions = Permission.objects.all().order_by('code')
    return render(request, 'accounts/permission_list.html', {'permissions': permissions})


@login_required
def notification_settings_view(request):
    """Allow any authenticated user to manage their own alert email preferences."""
    if request.method == 'POST':
        old_email = request.user.email
        request.user.email = request.POST.get('email', '').strip()
        request.user.notify_critical_alerts = request.POST.get('notify_critical_alerts') == 'on'
        request.user.notify_warning_alerts = request.POST.get('notify_warning_alerts') == 'on'
        request.user.save(update_fields=['email', 'notify_critical_alerts', 'notify_warning_alerts'])
        from audit.utils import write_audit
        write_audit(
            actor=request.user,
            action='account.notification_prefs_updated',
            entity_table='accounts_user',
            entity_id=request.user.pk,
            before={'email': old_email},
            after={
                'email': request.user.email,
                'notify_critical': request.user.notify_critical_alerts,
                'notify_warning': request.user.notify_warning_alerts,
            },
        )
        messages.success(request, "Notification preferences saved.")
        return redirect('accounts:notification_settings')
    return render(request, 'accounts/notification_settings.html', {'user': request.user})


@login_required
def sod_manage_view(request):
    if not request.user.is_staff:
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')
    from .models import SoDConflict, Permission

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            perm_a = request.POST['permission_a']
            perm_b = request.POST['permission_b']
            reason = request.POST.get('reason', '')
            if perm_a == perm_b:
                messages.error(request, "Cannot create a conflict between the same permission.")
            else:
                pa = get_object_or_404(Permission, pk=perm_a)
                pb = get_object_or_404(Permission, pk=perm_b)
                conflict, created = SoDConflict.objects.get_or_create(
                    permission_a=min(pa, pb, key=lambda p: p.pk),
                    permission_b=max(pa, pb, key=lambda p: p.pk),
                    defaults={'reason': reason},
                )
                if created:
                    from audit.utils import write_audit
                    write_audit(
                        actor=request.user,
                        action='account.sod_conflict_added',
                        entity_table='accounts_sodconflict',
                        entity_id=conflict.pk,
                        after={'permission_a': pa.code, 'permission_b': pb.code, 'reason': reason},
                    )
                messages.success(request, f"SoD conflict between '{pa.code}' and '{pb.code}' recorded.")
        elif action == 'delete':
            conflict_qs = SoDConflict.objects.filter(pk=request.POST['conflict_id'])
            if conflict_qs.exists():
                c_obj = conflict_qs.first()
                from audit.utils import write_audit
                write_audit(
                    actor=request.user,
                    action='account.sod_conflict_removed',
                    entity_table='accounts_sodconflict',
                    entity_id=c_obj.pk,
                    before={'permission_a': c_obj.permission_a.code, 'permission_b': c_obj.permission_b.code},
                )
                conflict_qs.delete()
            messages.success(request, "Conflict removed.")
        return redirect('accounts:sod_manage')

    permissions = Permission.objects.all().order_by('code')
    conflicts = SoDConflict.objects.select_related('permission_a', 'permission_b').all()
    return render(request, 'accounts/sod_manage.html', {
        'permissions': permissions,
        'conflicts': conflicts,
    })
