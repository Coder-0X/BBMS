import datetime
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from core.models import Branch
from .models import DemandFactDaily, Forecast, KpiDaily


@login_required
def analytics_dashboard(request):
    """Branch-level analytics: KPIs + 14-day demand forecast."""
    branch_param = request.GET.get('branch')
    if branch_param:
        try:
            branch_id = int(branch_param)
        except (ValueError, TypeError):
            branch_id = None
    else:
        branch_id = getattr(request.user, 'branch_id', None)
    branches = Branch.objects.filter(active=True)
    branch = get_object_or_404(Branch, pk=branch_id) if branch_id else branches.first()

    today = timezone.now().date()

    # Latest KPI row
    kpi = KpiDaily.objects.filter(branch=branch).order_by('-kpi_date').first()

    # 30-day trend per component
    trends = {}
    for cc in ['RBC', 'FFP', 'PLT']:
        facts = list(
            DemandFactDaily.objects.filter(
                branch=branch, component_class=cc,
                fact_date__gt=today - datetime.timedelta(days=30),
            ).order_by('fact_date').values('fact_date', 'units_issued', 'closing_stock')
        )
        trends[cc] = facts

    # Latest 14-day forecast
    forecasts = {}
    for cc in ['RBC', 'FFP', 'PLT']:
        rows = list(
            Forecast.objects.filter(
                branch=branch, component_class=cc,
                generated_on=today - datetime.timedelta(days=1),
            ).order_by('horizon_date').values('horizon_date', 'predicted_units', 'lower_80', 'upper_80')
        )
        if not rows:
            # Fall back to latest available forecast
            rows = list(
                Forecast.objects.filter(
                    branch=branch, component_class=cc,
                    horizon_date__gte=today,
                ).order_by('horizon_date').values('horizon_date', 'predicted_units', 'lower_80', 'upper_80')[:14]
            )
        forecasts[cc] = rows

    # Wastage summary (last 30 days)
    wastage = {}
    for cc in ['RBC', 'FFP', 'PLT']:
        facts30 = DemandFactDaily.objects.filter(
            branch=branch, component_class=cc,
            fact_date__gt=today - datetime.timedelta(days=30),
        )
        total_in = sum(f.units_received for f in facts30)
        total_wasted = sum(f.units_expired + f.units_discarded for f in facts30)
        pct = round(total_wasted / total_in * 100, 1) if total_in else None
        wastage[cc] = {'total_in': total_in, 'total_wasted': total_wasted, 'pct': pct}

    return render(request, 'analytics/dashboard.html', {
        'branch': branch,
        'branches': branches,
        'kpi': kpi,
        'trends': trends,
        'forecasts': forecasts,
        'wastage': wastage,
        'today': today,
    })
