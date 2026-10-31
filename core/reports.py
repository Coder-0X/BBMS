"""
Blood utilization reports.
All reports run as read-only DB queries — no writes, no side effects.
"""
from django.db.models import Count, Q, Avg, F, ExpressionWrapper, DurationField
from django.utils import timezone
from datetime import timedelta


def blood_utilization_report(branch, days=30) -> dict:
    """
    Classic blood bank utilization metrics for the past N days.
    Returns:
      - units_issued_by_component
      - units_transfused_by_component
      - units_wasted_by_component
      - crossmatch_to_transfusion_ratio (C:T) per component
      - crossmatch_to_transfusion_ratio (ideal ≤ 2.5 for RBC)
    """
    from inventory.models import BloodUnit
    from transfusion.models import IssueTransaction, Crossmatch

    cutoff = timezone.now() - timedelta(days=days)

    issued = (
        IssueTransaction.objects
        .filter(intended_branch=branch, issued_at__gte=cutoff)
        .values('blood_unit__component_class')
        .annotate(count=Count('id'))
    )

    crossmatched = (
        Crossmatch.objects
        .filter(request__branch=branch, performed_at__gte=cutoff,
                result__in=['compatible', 'electronic_release'])
        .values('blood_unit__component_class')
        .annotate(count=Count('id'))
    )

    transfused = (
        BloodUnit.objects
        .filter(owner_branch=branch, status='transfused')
        .values('component_class')
        .annotate(count=Count('id'))
    )

    wasted = (
        BloodUnit.objects
        .filter(owner_branch=branch, status='wasted')
        .values('component_class')
        .annotate(count=Count('id'))
    )

    expired = (
        BloodUnit.objects
        .filter(owner_branch=branch, status='expired')
        .values('component_class')
        .annotate(count=Count('id'))
    )

    # Build C:T ratio map
    crossmatch_map = {row['blood_unit__component_class']: row['count'] for row in crossmatched}
    issued_map     = {row['blood_unit__component_class']: row['count'] for row in issued}
    ct_ratios = {}
    for component, xm_count in crossmatch_map.items():
        tx_count = issued_map.get(component, 0)
        ct_ratios[component] = round(xm_count / tx_count, 2) if tx_count > 0 else None

    return {
        'period_days': days,
        'branch': str(branch),
        'issued': list(issued),
        'transfused': list(transfused),
        'wasted': list(wasted),
        'expired': list(expired),
        'crossmatch_to_transfusion_ratio': ct_ratios,
    }


def inventory_age_report(branch) -> list[dict]:
    """
    Show available units grouped by days until expiry.
    Helps identify units to prioritize for issue (FEFO — first expire, first out).
    """
    from inventory.models import BloodUnit
    now = timezone.now()
    units = BloodUnit.objects.filter(
        owner_branch=branch, status='available'
    ).values('did', 'component_class', 'abo_type', 'rh_d_type', 'expiry_datetime').order_by('expiry_datetime')

    result = []
    for u in units:
        if u['expiry_datetime']:
            days_left = (u['expiry_datetime'] - now).total_seconds() / 86400
            u['days_until_expiry'] = round(days_left, 1)
            u['urgency'] = 'critical' if days_left < 1 else ('warning' if days_left < 3 else 'ok')
        else:
            u['days_until_expiry'] = None
            u['urgency'] = 'unknown'
        result.append(u)
    return result


def donor_statistics_report(branch, days=90) -> dict:
    """Donation frequency and adverse event rates."""
    from donors.models import Donation, DonorAdverseEvent
    cutoff = timezone.now() - timedelta(days=days)

    donations = Donation.objects.filter(branch=branch, donated_at__gte=cutoff)
    by_type   = donations.values('donation_type').annotate(count=Count('id'))
    adverse   = DonorAdverseEvent.objects.filter(donation__branch=branch, recorded_at__gte=cutoff)
    by_severity = adverse.values('severity').annotate(count=Count('id'))

    total = donations.count()
    total_adverse = adverse.count()
    adverse_rate = round((total_adverse / total * 100), 2) if total else 0

    return {
        'period_days': days,
        'total_donations': total,
        'by_type': list(by_type),
        'adverse_events': total_adverse,
        'adverse_rate_pct': adverse_rate,
        'adverse_by_severity': list(by_severity),
    }


def tti_positivity_report(branch, days=90) -> list[dict]:
    """TTI reactive rate per test — key quality indicator."""
    from transfusion.models import DonationTestResult
    cutoff = timezone.now() - timedelta(days=days)

    results = (
        DonationTestResult.objects
        .filter(donation__branch=branch, performed_at__gte=cutoff)
        .values('test__test_code', 'test__name')
        .annotate(
            total=Count('id'),
            reactive=Count('id', filter=Q(result='reactive')),
        )
    )

    report = []
    for row in results:
        total = row['total']
        reactive = row['reactive']
        report.append({
            'test_code': row['test__test_code'],
            'test_name': row['test__name'],
            'total': total,
            'reactive': reactive,
            'rate_pct': round(reactive / total * 100, 3) if total else 0,
        })
    return report


def turnaround_time_report(branch, days=30) -> dict:
    """
    Transfusion Turnaround Time (TAT) report.

    AABB accreditation requires tracking:
      - TAT from request to first crossmatch
      - TAT from first crossmatch to issue
      - Total TAT request to issue
    Broken down by urgency level and component type.
    """
    from transfusion.models import BloodRequest, IssueTransaction, Crossmatch
    from django.db.models import Min, Avg, Max

    cutoff = timezone.now() - timedelta(days=days)

    requests = BloodRequest.objects.filter(
        branch=branch,
        requested_ts__gte=cutoff,
        crossmatch_started_ts__isnull=False,
    ).values(
        'pk', 'requested_ts', 'crossmatch_started_ts',
        'crossmatch_completed_ts', 'issued_ts',
        'urgency', 'component_class',
    )

    # Build per-request TAT rows
    rows = []
    for req in requests:
        req_ts  = req['requested_ts']
        xm_start = req['crossmatch_started_ts']
        xm_end   = req['crossmatch_completed_ts']
        issue_ts = req['issued_ts']

        req_to_xm_min   = int((xm_start  - req_ts).total_seconds() / 60) if xm_start else None
        xm_to_issue_min = int((issue_ts  - xm_end).total_seconds() / 60)  if (issue_ts and xm_end) else None
        total_min       = int((issue_ts  - req_ts).total_seconds() / 60)   if issue_ts else None

        rows.append({
            'request_pk':       req['pk'],
            'urgency':          req['urgency'],
            'component_class':  req['component_class'],
            'req_to_xm_min':    req_to_xm_min,
            'xm_to_issue_min':  xm_to_issue_min,
            'total_min':        total_min,
        })

    # Aggregate by urgency
    from collections import defaultdict
    by_urgency = defaultdict(lambda: {'count': 0, 'req_to_xm': [], 'total': []})
    for row in rows:
        u = row['urgency']
        by_urgency[u]['count'] += 1
        if row['req_to_xm_min'] is not None:
            by_urgency[u]['req_to_xm'].append(row['req_to_xm_min'])
        if row['total_min'] is not None:
            by_urgency[u]['total'].append(row['total_min'])

    def _stats(lst):
        if not lst:
            return {'avg': None, 'median': None, 'p90': None}
        s = sorted(lst)
        n = len(s)
        avg = round(sum(s) / n)
        median = s[n // 2]
        p90 = s[int(n * 0.9)]
        return {'avg': avg, 'median': median, 'p90': p90}

    urgency_summary = {
        u: {
            'count':      v['count'],
            'req_to_xm':  _stats(v['req_to_xm']),
            'total_tat':  _stats(v['total']),
        }
        for u, v in by_urgency.items()
    }

    # AABB targets (minutes): routine ≤ 60 min XM TAT; urgent ≤ 30; emergency ≤ 10
    TARGETS = {'routine': 60, 'urgent': 30, 'emergency_mtp': 10}
    for u, summary in urgency_summary.items():
        target = TARGETS.get(u, 60)
        avg = summary['req_to_xm']['avg']
        summary['target_min']    = target
        summary['meets_target']  = avg is not None and avg <= target

    return {
        'period_days':     days,
        'total_requests':  len(rows),
        'urgency_summary': urgency_summary,
        'rows':            rows[:50],  # detail rows capped for template
    }


def reaction_report(branch, days=90) -> dict:
    """Haemovigilance summary — reaction types and severity."""
    from transfusion.models import TransfusionReaction
    cutoff = timezone.now() - timedelta(days=days)

    reactions = TransfusionReaction.objects.filter(
        blood_unit__owner_branch=branch,
        recorded_at__gte=cutoff,
    )
    by_type     = reactions.values('reaction_type').annotate(count=Count('id'))
    by_severity = reactions.values('severity').annotate(count=Count('id'))
    by_outcome  = reactions.values('outcome').annotate(count=Count('id'))

    return {
        'period_days': days,
        'total_reactions': reactions.count(),
        'by_type': list(by_type),
        'by_severity': list(by_severity),
        'by_outcome': list(by_outcome),
    }


def quality_indicators_report(branch, days=30) -> dict:
    """
    ISO 15189:2022 / AABB Monthly Quality Indicators report.

    Key indicators:
      QI-1  Wastage rate (%) — target < 5%
      QI-2  C:T ratio — target < 2.5
      QI-3  Reaction rate per 1000 units issued
      QI-4  TAT compliance (% within target)
      QI-5  Near-expiry units (% inventory expiring within 72h)
      QI-6  QC pass rate (%)
      QI-7  Open NC rate (NCs not closed within 30 days)
      QI-8  SHOT-reportable events
    """
    from inventory.models import BloodUnit, WastageRecord
    from transfusion.models import TransfusionReaction, IssueTransaction, Crossmatch, Sample
    from quality.models import QCRun, NonConformance

    cutoff = timezone.now() - timedelta(days=days)
    now = timezone.now()

    # ── QI-1: Wastage rate ────────────────────────────────────────────────────
    issued = BloodUnit.objects.filter(
        owner_branch=branch,
        status='issued',
        created_at__gte=cutoff,
    ).count()
    wasted = WastageRecord.objects.filter(
        blood_unit__owner_branch=branch,
        recorded_at__gte=cutoff,
    ).count()
    total_processed = issued + wasted
    wastage_rate = round(wasted / total_processed * 100, 1) if total_processed else 0

    # ── QI-2: C:T ratio ───────────────────────────────────────────────────────
    crossmatches = Crossmatch.objects.filter(
        performed_at__gte=cutoff,
        tech__isnull=False,
    ).count()
    ct_ratio = round(crossmatches / issued, 2) if issued else 0

    # ── QI-3: Reaction rate ───────────────────────────────────────────────────
    reactions = TransfusionReaction.objects.filter(
        blood_unit__owner_branch=branch,
        recorded_at__gte=cutoff,
    ).count()
    reaction_rate = round(reactions / issued * 1000, 2) if issued else 0

    # ── QI-4: TAT compliance ──────────────────────────────────────────────────
    tat = turnaround_time_report(branch, days=days)
    tat_routine = tat.get('urgency_summary', {}).get('routine', {})
    # Compute % of routine requests that met the 60-min target
    tat_rows_routine = [r for r in tat.get('rows', []) if r.get('urgency') == 'routine']
    tat_within = sum(1 for r in tat_rows_routine if r.get('req_to_xm_min') is not None and r['req_to_xm_min'] <= 60)
    tat_compliant_pct = round(tat_within / len(tat_rows_routine) * 100, 1) if tat_rows_routine else None

    # ── QI-5: Near-expiry inventory ───────────────────────────────────────────
    near_expiry_cutoff = now + timedelta(hours=72)
    near_expiry = BloodUnit.objects.filter(
        owner_branch=branch,
        status='available',
        expiry_datetime__lte=near_expiry_cutoff,
        expiry_datetime__gt=now,
    ).count()
    available_total = BloodUnit.objects.filter(owner_branch=branch, status='available').count()
    near_expiry_pct = round(near_expiry / available_total * 100, 1) if available_total else 0

    # ── QI-6: QC pass rate ────────────────────────────────────────────────────
    qc_runs = QCRun.objects.filter(branch=branch, completed_at__gte=cutoff)
    qc_total = qc_runs.count()
    qc_passed = qc_runs.filter(overall_pass=True).count()
    qc_pass_rate = round(qc_passed / qc_total * 100, 1) if qc_total else None

    # ── QI-7: Open NC rate ────────────────────────────────────────────────────
    nc_opened = NonConformance.objects.filter(branch=branch, reported_at__gte=cutoff)
    nc_open_over_30 = nc_opened.filter(
        status__in=['open', 'under_review', 'capa_open', 'capa_verify'],
        reported_at__lte=now - timedelta(days=30),
    ).count()
    nc_total = nc_opened.count()

    # ── QI-8: SHOT-reportable ─────────────────────────────────────────────────
    shot_ncs = NonConformance.objects.filter(branch=branch, shot_reportable=True, reported_at__gte=cutoff).count()
    shot_reactions = TransfusionReaction.objects.filter(
        blood_unit__owner_branch=branch,
        recorded_at__gte=cutoff,
        # SHOT reportable: grade 3 (severe), 4 (life-threatening), 5 (fatal)
        severity__in=['grade_3', 'grade_4', 'grade_5'],
    ).count()

    return {
        'period_days': days,
        'branch': branch,
        'qi_wastage_rate': wastage_rate,
        'qi_wastage_target': 5.0,
        'qi_wastage_ok': wastage_rate <= 5.0,
        'qi_ct_ratio': ct_ratio,
        'qi_ct_target': 2.5,
        'qi_ct_ok': ct_ratio <= 2.5,
        'qi_reaction_rate': reaction_rate,
        'qi_reaction_target': 2.0,
        'qi_reaction_ok': reaction_rate <= 2.0,
        'qi_tat_compliant_pct': tat_compliant_pct,
        'qi_tat_target': 90,
        'qi_near_expiry_pct': near_expiry_pct,
        'qi_near_expiry_target': 10.0,
        'qi_near_expiry_ok': near_expiry_pct <= 10.0,
        'qi_qc_pass_rate': qc_pass_rate,
        'qi_qc_target': 100,
        'qi_nc_open_over_30': nc_open_over_30,
        'qi_nc_total': nc_total,
        'qi_shot_total': shot_ncs + shot_reactions,
        # Raw counts for dashboard display
        'issued': issued,
        'wasted': wasted,
        'crossmatches': crossmatches,
        'reactions': reactions,
        'near_expiry': near_expiry,
        'available_total': available_total,
        'qc_total': qc_total,
        'qc_passed': qc_passed,
    }
