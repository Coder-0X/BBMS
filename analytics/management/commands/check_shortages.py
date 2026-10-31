"""
management command: python manage.py check_shortages

Runs Holt-Winters forecasts for each component class / blood group at each branch
and raises critical alerts when stock will fall below safety level within 72 hours.

Run from cron daily (alongside build_daily_facts):
    30 1 * * *  python /path/manage.py check_shortages
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Branch


class Command(BaseCommand):
    help = 'Forecast demand and raise shortage alerts for the next 72h.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--horizon', type=int, default=3,
            help='Forecast horizon in days (default: 3)',
        )
        parser.add_argument(
            '--safety-days', type=float, default=1.5,
            help='Raise alert when projected days-of-supply < this value (default: 1.5)',
        )

    def handle(self, *args, **options):
        horizon = options['horizon']
        safety_days = options['safety_days']

        from analytics.models import Forecast, DemandFactDaily
        from inventory.models import BloodUnit
        from core.models import Alert

        for branch in Branch.objects.filter(active=True):
            self.stdout.write(f"Checking shortages for {branch.name}...")
            self._check_branch(branch, horizon, safety_days)

        self.stdout.write(self.style.SUCCESS("Shortage check complete."))

    def _check_branch(self, branch, horizon, safety_days):
        from analytics.models import Forecast, DemandFactDaily
        from analytics.forecasting import HoltWintersAdditive
        from inventory.models import BloodUnit
        from core.alerts import _raise_alert
        from django.db.models import Sum
        from datetime import timedelta, date

        components = ['RBC', 'PLT', 'FFP', 'CRYO']

        for component in components:
            # Current stock
            current_stock = BloodUnit.objects.filter(
                owner_branch=branch,
                component_class=component,
                status='available',
            ).count()

            # Get demand history from DemandFactDaily (last 28 days)
            cutoff = date.today() - timedelta(days=28)
            facts = list(
                DemandFactDaily.objects.filter(
                    branch=branch,
                    component_class=component,
                    fact_date__gte=cutoff,
                ).order_by('fact_date').values_list('units_issued', flat=True)
            )

            if len(facts) < 7:
                # Not enough data for Holt-Winters; use simple average
                avg_daily = sum(facts) / max(len(facts), 1) if facts else 1.0
                projected_demand = avg_daily * horizon
            else:
                try:
                    hw = HoltWintersAdditive(season_length=7)
                    hw.fit(facts)
                    forecast = hw.predict(horizon)
                    projected_demand = sum(forecast)
                except Exception:
                    avg_daily = sum(facts) / len(facts)
                    projected_demand = avg_daily * horizon

            projected_end_stock = max(0, current_stock - projected_demand)
            avg_daily_demand = projected_demand / horizon if horizon else 1
            projected_days_supply = (projected_end_stock / avg_daily_demand) if avg_daily_demand > 0 else float('inf')

            if projected_days_supply < safety_days:
                severity = 'critical' if projected_days_supply < 1.0 else 'warning'
                _raise_alert(
                    branch=branch,
                    alert_type='forecast_shortage',
                    severity=severity,
                    message=(
                        f"FORECAST SHORTAGE: {component} at {branch.name} — "
                        f"current stock {current_stock} units, projected demand {projected_demand:.1f} over "
                        f"{horizon} days → projected {projected_end_stock:.0f} units remaining "
                        f"({projected_days_supply:.1f} days supply). "
                        f"Safety threshold is {safety_days} days. Order additional stock."
                    ),
                    entity_table='inventory_bloodunit',
                    entity_id=hash(f"{branch.pk}-{component}-shortage") % 2147483647,
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"  [{severity.upper()}] {component}: stock={current_stock}, "
                        f"demand_3d={projected_demand:.1f}, projected={projected_end_stock:.0f} units"
                    )
                )
            else:
                self.stdout.write(
                    f"  OK {component}: stock={current_stock}, demand_3d≈{projected_demand:.1f}, "
                    f"projected_supply={projected_days_supply:.1f}d"
                )
