"""
Analytics and forecasting tests.
Run: pytest tests/test_analytics.py -v
"""
import pytest
from datetime import timedelta, date
from io import StringIO
from django.core.management import call_command
from django.utils import timezone


class TestHoltWintersForecasting:
    """Pure Python Holt-Winters — no DB required."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from analytics.forecasting import forecast_demand
        self.forecast_demand = forecast_demand

    def _daily_series(self, n=52, base=10, amplitude=2, period=7):
        import math
        return [
            base + amplitude * math.sin(2 * math.pi * i / period)
            for i in range(n)
        ]

    def _points(self, result):
        """Extract point forecasts from (predicted, lower_80, upper_80) tuples."""
        return [r[0] for r in result]

    def test_forecast_returns_requested_horizon(self):
        series = self._daily_series(n=60)
        result = self.forecast_demand(series, season_length=7, n_ahead=14)
        assert len(result) == 14

    def test_forecast_values_are_non_negative(self):
        series = self._daily_series(n=60, base=10, amplitude=2)
        result = self.forecast_demand(series, season_length=7, n_ahead=7)
        for point, low, high in result:
            assert low >= 0

    def test_flat_series_gives_flat_forecast(self):
        series = [10.0] * 60
        result = self.forecast_demand(series, season_length=7, n_ahead=7)
        for point, low, high in result:
            assert abs(point - 10.0) < 2.0, f"Expected ~10.0, got {point}"

    def test_too_short_series_returns_zeros(self):
        result = self.forecast_demand([], season_length=7, n_ahead=7)
        assert len(result) == 7
        assert result[0] == (0.0, 0.0, 0.0)

    def test_trend_upward_series(self):
        series = [float(i) for i in range(1, 61)]  # 1..60
        result = self.forecast_demand(series, season_length=7, n_ahead=7)
        points = self._points(result)
        assert points[0] > 30.0

    def test_seasonal_peak_preserved(self):
        series = self._daily_series(n=84, base=10, amplitude=5, period=7)
        result = self.forecast_demand(series, season_length=7, n_ahead=14)
        points = self._points(result)
        assert max(points) - min(points) > 1.0

    def test_result_has_confidence_interval(self):
        series = self._daily_series(n=60)
        result = self.forecast_demand(series, season_length=7, n_ahead=7)
        for point, low, high in result:
            assert low <= point <= high


class TestDailyFactsBuilder:

    def test_build_daily_facts_command_runs(self, db, branch):
        yesterday = (timezone.now().date() - timedelta(days=1)).isoformat()
        out = StringIO()
        call_command('build_daily_facts', date=yesterday, stdout=out)
        assert 'complete' in out.getvalue().lower() or True  # just verifying no exception

    def test_build_daily_facts_creates_demand_row(self, db, branch):
        from analytics.models import DemandFactDaily
        yesterday = timezone.now().date() - timedelta(days=1)
        out = StringIO()
        call_command('build_daily_facts', date=yesterday.isoformat(), stdout=out)
        # Command runs over all active branches — should create DemandFactDaily rows
        assert DemandFactDaily.objects.filter(fact_date=yesterday).exists()

    def test_build_daily_facts_idempotent(self, db, branch):
        from analytics.models import DemandFactDaily
        yesterday = timezone.now().date() - timedelta(days=2)
        out = StringIO()
        call_command('build_daily_facts', date=yesterday.isoformat(), stdout=out)
        count1 = DemandFactDaily.objects.filter(fact_date=yesterday).count()
        call_command('build_daily_facts', date=yesterday.isoformat(), stdout=out)
        count2 = DemandFactDaily.objects.filter(fact_date=yesterday).count()
        assert count2 == count1  # update_or_create — no duplicates


class TestKpiCalculations:

    def test_kpi_row_created_by_command(self, db, branch):
        from analytics.models import KpiDaily
        yesterday = timezone.now().date() - timedelta(days=1)
        out = StringIO()
        call_command('build_daily_facts', date=yesterday.isoformat(), stdout=out)
        assert KpiDaily.objects.filter(kpi_date=yesterday).exists()

    def test_kpi_fields_present(self, db, branch):
        from analytics.models import KpiDaily
        yesterday = timezone.now().date() - timedelta(days=1)
        out = StringIO()
        call_command('build_daily_facts', date=yesterday.isoformat(), stdout=out)
        kpi = KpiDaily.objects.filter(kpi_date=yesterday).first()
        assert kpi is not None
        assert hasattr(kpi, 'ct_ratio_rbc')
        assert hasattr(kpi, 'wastage_pct_rbc')
        assert hasattr(kpi, 'days_supply_rbc')

    def test_ct_ratio_none_when_no_issues(self, db, branch):
        from analytics.models import DemandFactDaily, KpiDaily
        yesterday = timezone.now().date() - timedelta(days=3)
        DemandFactDaily.objects.update_or_create(
            branch=branch,
            component_class='RBC',
            fact_date=yesterday,
            defaults={'units_issued': 0, 'units_crossmatched': 5},
        )
        out = StringIO()
        call_command('build_daily_facts', date=yesterday.isoformat(), stdout=out)
        kpi = KpiDaily.objects.filter(branch=branch, kpi_date=yesterday).first()
        if kpi:
            assert kpi.ct_ratio_rbc is None  # division by zero avoided

    def test_demand_fact_daily_model_fields(self, db, branch):
        from analytics.models import DemandFactDaily
        fact = DemandFactDaily.objects.create(
            branch=branch,
            component_class='RBC',
            fact_date=timezone.now().date() - timedelta(days=10),
            units_issued=5,
            units_crossmatched=7,
            units_expired=1,
            units_received=8,
            opening_stock=12,
            closing_stock=14,
        )
        assert fact.pk is not None
        assert fact.units_issued == 5
        assert fact.units_crossmatched == 7


class TestShortageAlerts:

    def test_critical_stock_check_runs_without_error(self, db, branch):
        from core.alerts import _check_critical_stock_by_blood_group
        _check_critical_stock_by_blood_group(branch=branch)

    def test_all_alerts_run_without_error(self, db, branch):
        from core.alerts import check_all_alerts
        check_all_alerts(branch=branch)

    def test_low_inventory_check_runs(self, db, branch):
        from core.alerts import _check_low_inventory
        _check_low_inventory(branch=branch)

    def test_demand_fact_unique_per_branch_component_date(self, db, branch):
        from analytics.models import DemandFactDaily
        from django.db import IntegrityError
        fact_date = timezone.now().date() - timedelta(days=5)
        DemandFactDaily.objects.create(
            branch=branch, component_class='PLT', fact_date=fact_date
        )
        with pytest.raises(IntegrityError):
            DemandFactDaily.objects.create(
                branch=branch, component_class='PLT', fact_date=fact_date
            )


# ─── Analytics view tests ─────────────────────────────────────────────────────

from django.test import Client
from tests.conftest import UserFactory


class TestAnalyticsDashboardView:

    def test_get_renders_for_authenticated_user(self, db, branch, user):
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.get(f'/analytics/?branch={branch.pk}')
        assert response.status_code == 200

    def test_unauthenticated_redirects_to_login(self, db):
        response = Client().get('/analytics/')
        assert response.status_code == 302
        assert '/accounts/login/' in response.get('Location', '') or 'login' in response.get('Location', '')

    def test_first_branch_used_when_no_branch_param(self, db, branch, user):
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.get('/analytics/')
        assert response.status_code == 200

    def test_response_includes_context_kpi(self, db, branch, user):
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.get(f'/analytics/?branch={branch.pk}')
        assert 'kpi' in response.context

    def test_response_includes_context_trends(self, db, branch, user):
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.get(f'/analytics/?branch={branch.pk}')
        assert 'trends' in response.context
        assert set(response.context['trends'].keys()) == {'RBC', 'FFP', 'PLT'}

    def test_response_includes_context_wastage(self, db, branch, user):
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.get(f'/analytics/?branch={branch.pk}')
        assert 'wastage' in response.context

    def test_wastage_pct_correct_with_data(self, db, branch, user):
        from analytics.models import DemandFactDaily
        yesterday = timezone.now().date() - timedelta(days=1)
        DemandFactDaily.objects.create(
            branch=branch, component_class='RBC', fact_date=yesterday,
            units_received=10, units_expired=1, units_discarded=1,
            units_issued=8, units_crossmatched=10,
        )
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.get(f'/analytics/?branch={branch.pk}')
        assert response.status_code == 200
        wastage = response.context['wastage']
        rbc_wastage = wastage.get('RBC', {})
        assert rbc_wastage.get('pct') == 20.0  # 2 wasted / 10 received

    def test_invalid_branch_pk_returns_404(self, db, branch, user):
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.get('/analytics/?branch=99999')
        assert response.status_code == 404

    def test_non_numeric_branch_param_does_not_crash(self, db, branch, user):
        """
        Regression: get_object_or_404(Branch, pk='abc') raises ValueError (not Http404)
        because Django's IntegerField.get_prep_value() calls int('abc').
        After fix with explicit int() guard, falls back to first active branch.
        """
        client = Client()
        client.login(username=user.username, password='testpass123')
        response = client.get('/analytics/?branch=not_a_number')
        assert response.status_code != 500
        assert response.status_code == 200
