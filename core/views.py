from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.utils import timezone
from datetime import timedelta

from .models import Alert, Branch, ConfigTarget, MCIEvent
from .reports import blood_utilization_report, inventory_age_report, donor_statistics_report, tti_positivity_report, reaction_report, turnaround_time_report, quality_indicators_report


def _safe_int(value, default=0):
    """Convert *value* to int, returning *default* on ValueError/TypeError."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


@login_required
def dashboard(request):
    branch_id = request.session.get('branch_id')
    if not branch_id:
        # Auto-select first branch for now; Phase 3 will add branch selection
        branch = Branch.objects.first()
        if branch:
            request.session['branch_id'] = branch.pk
        else:
            return render(request, 'dashboard.html', {'stats': {}, 'alerts': [], 'inventory_summary': [], 'pending_emergency': [], 'branch': None})
    else:
        branch = Branch.objects.filter(pk=branch_id).first()
        if branch is None:
            # Branch was deleted while session still referenced it — reset
            del request.session['branch_id']
            return redirect('core:dashboard')

    from inventory.models import BloodUnit, COMPONENT_CLASSES
    from transfusion.models import BloodRequest, EmergencyRelease

    from inventory.models import BloodUnit, COMPONENT_CLASSES
    from transfusion.models import BloodRequest, EmergencyRelease, IssueTransaction
    from patients.models import Patient

    now = timezone.now()

    # ── Core stats ───────────────────────────────────────────────────────────
    available_units = BloodUnit.objects.filter(owner_branch=branch, status='available').count()
    in_testing      = BloodUnit.objects.filter(owner_branch=branch, status='in_testing').count()
    quarantined     = BloodUnit.objects.filter(owner_branch=branch, status='quarantined').count()
    pending_requests = BloodRequest.objects.filter(branch=branch, outcome='unmet').count()
    unread_alerts   = Alert.objects.filter(branch=branch, acknowledged_at__isnull=True).count()

    # Issues today
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    issues_today = IssueTransaction.objects.filter(intended_branch=branch, issued_at__gte=today_start).count()

    stats = {
        'available_units': available_units,
        'in_testing': in_testing,
        'quarantined': quarantined,
        'pending_requests': pending_requests,
        'unread_alerts': unread_alerts,
        'issues_today': issues_today,
    }

    # ── Alerts — unacknowledged ───────────────────────────────────────────────
    alerts = Alert.objects.filter(branch=branch, acknowledged_at__isnull=True).order_by('-created_at')[:8]

    # ── Inventory by component ────────────────────────────────────────────────
    inventory_summary = []
    expiry_24h = now + timedelta(hours=24)
    expiry_72h = now + timedelta(hours=72)
    for code, label in COMPONENT_CLASSES:
        available = BloodUnit.objects.filter(owner_branch=branch, component_class=code, status='available').count()
        reserved  = BloodUnit.objects.filter(owner_branch=branch, component_class=code, status__in=['reserved','crossmatched']).count()
        expiring_24 = BloodUnit.objects.filter(owner_branch=branch, component_class=code, status='available', expiry_datetime__lte=expiry_24h).count()
        expiring_72 = BloodUnit.objects.filter(owner_branch=branch, component_class=code, status='available', expiry_datetime__lte=expiry_72h).count()
        if available or reserved:
            inventory_summary.append({
                'component_class': code,
                'label': label,
                'available': available,
                'reserved': reserved,
                'expiring_24h': expiring_24 or 0,
                'expiring_72h': expiring_72 or 0,
            })

    # ── Inventory by blood group (ABO/Rh) ────────────────────────────────────
    abo_rh_stock = []
    for abo in ('O', 'A', 'B', 'AB'):
        for rh in ('neg', 'pos'):
            count = BloodUnit.objects.filter(
                owner_branch=branch,
                status='available',
                abo_type=abo,
                rh_d_type=rh,
                component_class='RBC',
            ).count()
            abo_rh_stock.append({
                'abo': abo,
                'rh': rh,
                'label': f"{abo}{'−' if rh=='neg' else '+'}",
                'count': count,
            })

    # ── Ungrouped units alert ─────────────────────────────────────────────────
    from datetime import timedelta as _td
    ungrouped_cutoff = now - _td(hours=24)
    ungrouped_units_count = BloodUnit.objects.filter(
        owner_branch=branch,
        status__in=['quarantined', 'in_testing'],
        created_at__lte=ungrouped_cutoff,
        abo_type='',
    ).count()

    # ── Requests without guideline check (last 7 days, non-emergency) ────────
    from transfusion.models import BloodRequest, TransfusionGuidelineCheck
    _seven_days_ago = now - _td(days=7)
    requests_needing_cds = BloodRequest.objects.filter(
        branch_id=branch_id,
        requested_ts__gte=_seven_days_ago,
        urgency__in=['routine', 'urgent'],
    ).exclude(guideline_check__isnull=False).count()

    # ── Near-expiry units (within 72 h) ──────────────────────────────────────
    near_expiry_cutoff = now + _td(hours=72)
    near_expiry_units = BloodUnit.objects.filter(
        owner_branch=branch,
        status='available',
        expiry_datetime__lte=near_expiry_cutoff,
        expiry_datetime__gt=now,
    ).order_by('expiry_datetime')[:10]

    # ── Open non-conformances ─────────────────────────────────────────────────
    from quality.models import NonConformance
    open_nc_count = NonConformance.objects.filter(
        branch=branch,
        status__in=['open', 'under_review', 'capa_open', 'capa_verify'],
    ).count()

    # ── Open blood group discrepancy investigations ───────────────────────────
    from patients.models import BloodGroupDiscrepancyInvestigation
    open_discrepancies = BloodGroupDiscrepancyInvestigation.objects.filter(
        branch=branch, status__in=['open', 'escalated'],
    ).count()

    # ── Reagent low-stock alerts ──────────────────────────────────────────────
    from quality.models import Reagent
    from django.db.models import Count, Q
    low_stock_reagents = []
    for reagent in Reagent.objects.filter(active=True):
        available_lots = reagent.lots.filter(
            branch=branch,
            status__in=['in_use', 'quarantined'],
        ).count()
        if available_lots < reagent.minimum_lots:
            low_stock_reagents.append({
                'reagent': reagent,
                'available_lots': available_lots,
                'minimum_lots': reagent.minimum_lots,
            })

    # ── Active MTP activations ────────────────────────────────────────────────
    from transfusion.models import MTPActivation
    active_mtp = MTPActivation.objects.filter(branch=branch, status='active').order_by('-activated_at')

    # ── Active MCI ────────────────────────────────────────────────────────────
    active_mci = MCIEvent.active_for_branch(branch_id)

    # ── Pending emergency signoffs ────────────────────────────────────────────
    pending_emergency = EmergencyRelease.objects.filter(
        request__branch=branch,
        signoff_status='pending',
    ).select_related('patient').order_by('release_datetime')[:5]

    # ── Recent transfusions ───────────────────────────────────────────────────
    recent_issues = IssueTransaction.objects.filter(
        intended_branch=branch,
    ).select_related('patient', 'blood_unit').order_by('-issued_at')[:6]

    return render(request, 'dashboard.html', {
        'branch': branch,
        'stats': stats,
        'alerts': alerts,
        'inventory_summary': inventory_summary,
        'abo_rh_stock': abo_rh_stock,
        'pending_emergency': pending_emergency,
        'recent_issues': recent_issues,
        'unread_alert_count': unread_alerts,
        'active_mci': active_mci,
        'active_mtp': active_mtp,
        'ungrouped_units_count': ungrouped_units_count,
        'near_expiry_units': near_expiry_units,
        'requests_needing_cds': requests_needing_cds,
        'low_stock_reagents': low_stock_reagents,
        'open_discrepancies': open_discrepancies,
        'open_nc_count': open_nc_count,
    })


@login_required
def reports_view(request):
    branch_id = request.session.get('branch_id')
    branch = get_object_or_404(Branch, pk=branch_id) if branch_id else Branch.objects.first()
    days = _safe_int(request.GET.get('days', 30), 30)

    return render(request, 'core/reports.html', {
        'branch': branch,
        'period_days': days,
        'utilization': blood_utilization_report(branch, days),
        'inventory_age': inventory_age_report(branch),
        'donor_stats': donor_statistics_report(branch, days),
        'tti': tti_positivity_report(branch, days),
        'reactions': reaction_report(branch, days),
    })


@login_required
def export_report_pdf(request, report_type):
    from .pdf_reports import (
        render_utilization_pdf, render_inventory_age_pdf,
        render_donor_stats_pdf, render_tti_pdf, render_reaction_pdf,
    )
    branch_id = request.session.get('branch_id')
    branch = get_object_or_404(Branch, pk=branch_id) if branch_id else Branch.objects.first()
    days = _safe_int(request.GET.get('days', 30), 30)
    branch_name = branch.name if branch else 'Unknown Branch'

    RENDERERS = {
        'utilization': (blood_utilization_report, render_utilization_pdf, True),
        'inventory': (inventory_age_report, render_inventory_age_pdf, False),
        'donors': (donor_statistics_report, render_donor_stats_pdf, True),
        'tti': (tti_positivity_report, render_tti_pdf, False),
        'reactions': (reaction_report, render_reaction_pdf, True),
    }

    if report_type not in RENDERERS:
        return HttpResponse("Unknown report type", status=404)

    data_fn, render_fn, uses_days = RENDERERS[report_type]
    data = data_fn(branch, days) if uses_days else data_fn(branch)
    pdf_bytes = render_fn(data, branch_name)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f'bloodbank_{report_type}_report.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def branch_list(request):
    branches = Branch.objects.all().order_by('name')
    return render(request, 'core/branch_list.html', {'branches': branches})


@login_required
def branch_create(request):
    if not request.user.is_staff:
        from django.contrib import messages as _msg
        _msg.error(request, "Only administrators can create new branches.")
        return redirect('core:branch_list')
    if request.method == 'POST':
        from audit.utils import write_audit
        branch = Branch.objects.create(
            name=request.POST['name'],
            facility_code=request.POST['facility_code'].upper()[:3],
            address=request.POST.get('address', ''),
            timezone=request.POST.get('timezone', 'UTC'),
            active=True,
        )
        write_audit(
            actor=request.user,
            action='branch.create',
            entity_table='core_branch',
            entity_id=branch.pk,
            after={'name': branch.name, 'facility_code': branch.facility_code},
        )
        from django.contrib import messages
        messages.success(request, f"Branch '{branch.name}' created.")
        return redirect('core:branch_list')
    return render(request, 'core/branch_form.html')


@login_required
def select_branch(request):
    """Let users switch their active branch for the session."""
    if request.method == 'POST':
        branch_id = request.POST.get('branch_id')
        try:
            branch_id_int = int(branch_id) if branch_id else None
        except (ValueError, TypeError):
            branch_id_int = None
        if branch_id_int and Branch.objects.filter(pk=branch_id_int, active=True).exists():
            request.session['branch_id'] = branch_id_int
            from django.contrib import messages
            messages.success(request, "Branch switched.")
        return redirect('core:dashboard')

    branches = Branch.objects.filter(active=True).order_by('name')
    return render(request, 'core/select_branch.html', {
        'branches': branches,
        'current_branch_id': request.session.get('branch_id'),
    })


@login_required
def audit_log_view(request):
    if not request.user.is_staff:
        from django.contrib import messages as msg_mod
        msg_mod.error(request, "Permission denied — staff only.")
        return redirect('core:dashboard')

    from audit.models import AuditLog
    from django.core.paginator import Paginator
    qs = AuditLog.objects.select_related('actor').order_by('-occurred_at_utc')

    action_filter = request.GET.get('action', '').strip()
    actor_filter = request.GET.get('actor', '').strip()
    table_filter = request.GET.get('table', '').strip()
    if action_filter:
        qs = qs.filter(action__icontains=action_filter)
    if actor_filter:
        qs = qs.filter(actor__username__icontains=actor_filter)
    if table_filter:
        qs = qs.filter(entity_table__icontains=table_filter)

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/audit_log.html', {
        'page_obj': page,
        'action_filter': action_filter,
        'actor_filter': actor_filter,
        'table_filter': table_filter,
    })


@login_required
def config_target_list(request):
    """List all ConfigTarget rows for the active branch."""
    if not request.user.is_staff:
        from django.contrib import messages as msg_mod
        msg_mod.error(request, "Permission denied — staff only.")
        return redirect('core:dashboard')
    branch_id = request.session.get('branch_id')
    branch = get_object_or_404(Branch, pk=branch_id) if branch_id else Branch.objects.first()
    targets = ConfigTarget.objects.filter(branch=branch).order_by('component_class')
    return render(request, 'core/config_target_list.html', {
        'branch': branch,
        'targets': targets,
        'component_choices': ConfigTarget.CLASSES,
    })


@login_required
def config_target_form(request, pk=None):
    """Create or edit a ConfigTarget."""
    if not request.user.is_staff:
        from django.contrib import messages as msg_mod
        msg_mod.error(request, "Permission denied — staff only.")
        return redirect('core:dashboard')
    branch_id = request.session.get('branch_id')
    branch = get_object_or_404(Branch, pk=branch_id) if branch_id else Branch.objects.first()
    target = get_object_or_404(ConfigTarget, pk=pk) if pk else None
    from audit.utils import write_audit
    from django.contrib import messages as msg_mod

    if request.method == 'POST':
        component_class = request.POST.get('component_class', '')
        data = {
            'branch': branch,
            'component_class': component_class,
            'target_days_of_supply': request.POST.get('target_days_of_supply', 3.0),
            'max_wastage_pct': request.POST.get('max_wastage_pct', 5.0),
            'near_expiry_alert_hours': request.POST.get('near_expiry_alert_hours', 72),
            'max_ct_ratio': request.POST.get('max_ct_ratio', 2.5),
            'safety_quantile': request.POST.get('safety_quantile', 0.950),
        }
        if target:
            before = {
                'target_days_of_supply': str(target.target_days_of_supply),
                'max_wastage_pct': str(target.max_wastage_pct),
                'near_expiry_alert_hours': target.near_expiry_alert_hours,
                'max_ct_ratio': str(target.max_ct_ratio),
            }
            for field, value in data.items():
                if field not in ('branch', 'component_class'):
                    setattr(target, field, value)
            target.save()
            write_audit(actor=request.user, action='config_target.update',
                        entity_table='core_configtarget', entity_id=target.pk,
                        before=before, after={'component_class': target.component_class},
                        branch=branch)
            msg_mod.success(request, f"KPI targets for {target.component_class} updated.")
        else:
            target = ConfigTarget.objects.create(**data)
            write_audit(actor=request.user, action='config_target.create',
                        entity_table='core_configtarget', entity_id=target.pk,
                        after={'component_class': component_class}, branch=branch)
            msg_mod.success(request, f"KPI targets for {component_class} created.")
        return redirect('core:config_target_list')

    return render(request, 'core/config_target_form.html', {
        'branch': branch,
        'target': target,
        'component_choices': ConfigTarget.CLASSES,
    })


@login_required
def config_target_delete(request, pk):
    if not request.user.is_staff:
        from django.contrib import messages as msg_mod
        msg_mod.error(request, "Permission denied — staff only.")
        return redirect('core:dashboard')
    target = get_object_or_404(ConfigTarget, pk=pk)
    from audit.utils import write_audit
    from django.contrib import messages as msg_mod
    if request.method == 'POST':
        branch = target.branch
        label = target.component_class
        write_audit(actor=request.user, action='config_target.delete',
                    entity_table='core_configtarget', entity_id=target.pk,
                    before={'component_class': label}, branch=branch)
        target.delete()
        msg_mod.success(request, f"KPI target for {label} deleted.")
        return redirect('core:config_target_list')
    return render(request, 'core/config_target_confirm_delete.html', {'target': target})


@login_required
def audit_chain_verify(request):
    """Run the hash-chain integrity check and display the result."""
    if not request.user.is_staff:
        from django.contrib import messages as msg_mod
        msg_mod.error(request, "Permission denied — staff only.")
        return redirect('core:dashboard')
    from audit.utils import verify_chain
    from audit.models import AuditLog
    is_valid, message = verify_chain()
    total_entries = AuditLog.objects.count()
    return render(request, 'core/audit_chain_verify.html', {
        'is_valid': is_valid,
        'message': message,
        'total_entries': total_entries,
    })


@login_required
def alerts_view(request):
    branch_id = request.session.get('branch_id')
    branch = get_object_or_404(Branch, pk=branch_id) if branch_id else Branch.objects.first()
    from django.core.paginator import Paginator
    from django.contrib import messages as msg_mod

    qs = Alert.objects.filter(branch=branch).order_by('-created_at')

    severity_filter = request.GET.get('severity', '')
    acknowledged_filter = request.GET.get('acked', '')
    if severity_filter:
        qs = qs.filter(severity=severity_filter)
    if acknowledged_filter == '0':
        qs = qs.filter(acknowledged_at__isnull=True)
    elif acknowledged_filter == '1':
        qs = qs.filter(acknowledged_at__isnull=False)

    if request.method == 'POST':
        from audit.utils import write_audit
        action = request.POST.get('action')
        if action == 'acknowledge':
            try:
                alert_pk = int(request.POST.get('alert_id'))
            except (ValueError, TypeError):
                alert_pk = None
            if alert_pk:
                updated = Alert.objects.filter(
                    pk=alert_pk, branch=branch, acknowledged_at__isnull=True
                ).update(acknowledged_at=timezone.now(), acknowledged_by=request.user)
                if updated:
                    write_audit(
                        actor=request.user,
                        action='alert.acknowledge',
                        entity_table='core_alert',
                        entity_id=alert_pk,
                        after={'acknowledged_by': request.user.pk},
                        branch=branch,
                    )
            msg_mod.success(request, "Alert acknowledged.")
        elif action == 'acknowledge_all':
            ids = list(
                Alert.objects.filter(branch=branch, acknowledged_at__isnull=True)
                .values_list('pk', flat=True)
            )
            Alert.objects.filter(pk__in=ids).update(
                acknowledged_at=timezone.now(),
                acknowledged_by=request.user,
            )
            if ids:
                write_audit(
                    actor=request.user,
                    action='alert.acknowledge_all',
                    entity_table='core_alert',
                    entity_id=branch.pk,
                    after={'count': len(ids), 'branch': branch.pk},
                    branch=branch,
                )
            msg_mod.success(request, "All active alerts acknowledged.")
        return redirect('core:alerts')

    paginator = Paginator(qs, 30)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/alerts.html', {
        'page_obj': page,
        'branch': branch,
        'severity_filter': severity_filter,
        'acknowledged_filter': acknowledged_filter,
        'unacked_count': Alert.objects.filter(branch=branch, acknowledged_at__isnull=True).count(),
    })


@login_required
def mci_status(request):
    """MCI control panel — activate or stand down."""
    from accounts.permissions import has_permission
    from django.contrib import messages as msg_mod
    branch_id = request.session.get('branch_id')
    branch = get_object_or_404(Branch, pk=branch_id) if branch_id else Branch.objects.first()
    active_mci = MCIEvent.active_for_branch(branch_id)

    if request.method == 'POST':
        if not has_permission(request.user, 'mci.activate', branch_id):
            msg_mod.error(request, "Permission denied — MCI authorisation required.")
            return redirect('core:mci')

        action = request.POST.get('action')
        reauth_at = request.session.get('reauth_at')

        if action == 'activate' and not active_mci:
            from .mci import activate_mci
            try:
                mci = activate_mci(
                    branch_id=branch_id,
                    level=request.POST.get('level', '2'),
                    incident_name=request.POST.get('incident_name', '').strip(),
                    actor=request.user,
                    notes=request.POST.get('notes', ''),
                    reauth_at=reauth_at,
                )
                msg_mod.warning(request, f"MCI-{mci.pk} ACTIVATED. O-neg units pre-allocated. All staff alerted.")
            except ValueError as e:
                msg_mod.error(request, str(e))

        elif action == 'standdown' and active_mci:
            from .mci import standdown_mci
            try:
                standdown_mci(active_mci, request.user, notes=request.POST.get('notes', ''), reauth_at=reauth_at)
                msg_mod.success(request, f"MCI-{active_mci.pk} stood down. Pre-allocated units released.")
            except ValueError as e:
                msg_mod.error(request, str(e))

        return redirect('core:mci')

    recent_events = MCIEvent.objects.filter(branch=branch).order_by('-activated_at')[:10]
    return render(request, 'core/mci.html', {
        'branch': branch,
        'active_mci': active_mci,
        'recent_events': recent_events,
        'mci_levels': MCIEvent.LEVELS,
    })


@login_required
def tat_report(request):
    """Turnaround Time (TAT) report — AABB accreditation metric."""
    branch_id = request.session.get('branch_id')
    branch = get_object_or_404(Branch, pk=branch_id) if branch_id else Branch.objects.first()
    days = _safe_int(request.GET.get('days', 30), 30)
    data = turnaround_time_report(branch, days)

    # Pre-resolve urgency labels for template display
    URGENCY_LABELS = {
        'routine': 'Routine',
        'urgent': 'Urgent',
        'emergency_mtp': 'Emergency / MTP',
    }
    urgency_resolved = [
        {
            'code': code,
            'label': URGENCY_LABELS.get(code, code),
            **stats,
        }
        for code, stats in data['urgency_summary'].items()
    ]
    urgency_resolved.sort(key=lambda x: ['emergency_mtp', 'urgent', 'routine'].index(x['code'])
                          if x['code'] in ['emergency_mtp', 'urgent', 'routine'] else 99)

    return render(request, 'core/tat_report.html', {
        'branch': branch,
        'period_days': days,
        'total_requests': data['total_requests'],
        'urgency_summary': urgency_resolved,
        'detail_rows': data['rows'],
    })


@login_required
def quality_indicators(request):
    """Monthly Quality Indicators dashboard — ISO 15189 / AABB QI programme."""
    branch_id = request.session.get('branch_id')
    branch = get_object_or_404(Branch, pk=branch_id) if branch_id else Branch.objects.first()
    days = _safe_int(request.GET.get('days', 30), 30)
    data = quality_indicators_report(branch, days)
    return render(request, 'core/quality_indicators.html', {
        'branch': branch,
        'days': days,
        **data,
    })
