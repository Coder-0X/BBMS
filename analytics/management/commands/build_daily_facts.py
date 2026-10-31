"""
management command: python manage.py build_daily_facts [--date YYYY-MM-DD]

Run nightly (e.g. 01:00) to backfill DemandFactDaily rows and update KpiDaily.
If --date is omitted, processes yesterday.

Cron example:
    0 1 * * *  /path/to/venv/bin/python /path/to/manage.py build_daily_facts
"""
import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count

from core.models import Branch
from analytics.models import DemandFactDaily, KpiDaily, Forecast
from analytics.forecasting import forecast_demand


COMPONENT_CLASSES = ['RBC', 'FFP', 'PLT', 'CRYO', 'WB', 'GRAN']
SEASON_LENGTH = 7
FORECAST_HORIZON = 14  # days ahead


class Command(BaseCommand):
    help = 'Build DemandFactDaily + KpiDaily rows, then run demand forecasts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', type=str, default=None,
            help='YYYY-MM-DD to process (default: yesterday)',
        )
        parser.add_argument(
            '--all-history', action='store_true',
            help='Rebuild all history (slow — only for initial setup)',
        )
        parser.add_argument(
            '--optimise', action='store_true',
            help='Grid-search Holt-Winters params (slower but better accuracy)',
        )

    def handle(self, *args, **options):
        if options['all_history']:
            self._build_all_history(options['optimise'])
            return

        target = options['date']
        if target:
            fact_date = datetime.date.fromisoformat(target)
        else:
            fact_date = (timezone.now() - datetime.timedelta(days=1)).date()

        for branch in Branch.objects.filter(active=True):
            for cc in COMPONENT_CLASSES:
                self._build_fact(branch, cc, fact_date)
            self._update_kpi(branch, fact_date)
            self._run_forecast(branch, fact_date, options['optimise'])
            self.stdout.write(f"Done: {branch.name} / {fact_date}")

        self.stdout.write(self.style.SUCCESS("build_daily_facts complete."))

    def _build_all_history(self, optimise):
        from transfusion.models import IssueTransaction
        from inventory.models import BloodUnit

        earliest_tx = IssueTransaction.objects.order_by('issued_at').first()
        if not earliest_tx:
            self.stdout.write("No transactions found — nothing to build.")
            return

        start = earliest_tx.issued_at.date()
        end = (timezone.now() - datetime.timedelta(days=1)).date()
        current = start

        while current <= end:
            for branch in Branch.objects.filter(active=True):
                for cc in COMPONENT_CLASSES:
                    self._build_fact(branch, cc, current)
                self._update_kpi(branch, current)
                self._run_forecast(branch, current, optimise)
            current += datetime.timedelta(days=1)
            if (current - start).days % 30 == 0:
                self.stdout.write(f"  ... processed up to {current}")

        self.stdout.write(self.style.SUCCESS("History build complete."))

    def _build_fact(self, branch, component_class, fact_date):
        from transfusion.models import IssueTransaction, Crossmatch
        from inventory.models import BloodUnit

        day_start = datetime.datetime.combine(fact_date, datetime.time.min,
                                              tzinfo=datetime.timezone.utc)
        day_end   = datetime.datetime.combine(fact_date, datetime.time.max,
                                              tzinfo=datetime.timezone.utc)

        units_issued = IssueTransaction.objects.filter(
            intended_branch=branch,
            blood_unit__component_class=component_class,
            issued_at__range=(day_start, day_end),
        ).count()

        units_crossmatched = Crossmatch.objects.filter(
            sample__branch=branch,
            blood_unit__component_class=component_class,
            performed_at__range=(day_start, day_end),
        ).count()

        units_expired = BloodUnit.objects.filter(
            owner_branch=branch,
            component_class=component_class,
            status='expired',
            expiry_datetime__range=(day_start, day_end),
        ).count()

        units_discarded = BloodUnit.objects.filter(
            owner_branch=branch,
            component_class=component_class,
            status='destroyed',
            updated_at__range=(day_start, day_end),
        ).count() if hasattr(BloodUnit, 'updated_at') else 0

        units_received = BloodUnit.objects.filter(
            owner_branch=branch,
            component_class=component_class,
            created_at__range=(day_start, day_end),
        ).count()

        opening_stock = BloodUnit.objects.filter(
            owner_branch=branch,
            component_class=component_class,
            created_at__lt=day_start,
            status='available',
        ).count()

        closing_stock = BloodUnit.objects.filter(
            owner_branch=branch,
            component_class=component_class,
            status='available',
        ).count()

        DemandFactDaily.objects.update_or_create(
            branch=branch,
            component_class=component_class,
            fact_date=fact_date,
            defaults=dict(
                units_issued=units_issued,
                units_crossmatched=units_crossmatched,
                units_expired=units_expired,
                units_discarded=units_discarded,
                units_received=units_received,
                opening_stock=opening_stock,
                closing_stock=closing_stock,
            ),
        )

    def _update_kpi(self, branch, kpi_date):
        from analytics.models import DemandFactDaily

        def _ct(cc):
            fact = DemandFactDaily.objects.filter(branch=branch, component_class=cc,
                                                   fact_date=kpi_date).first()
            if not fact or not fact.units_issued:
                return None
            return round(fact.units_crossmatched / fact.units_issued, 2)

        def _wastage(cc):
            facts = DemandFactDaily.objects.filter(
                branch=branch, component_class=cc,
                fact_date__lte=kpi_date,
            ).order_by('-fact_date')[:30]
            total_in = sum(f.units_received for f in facts)
            total_wasted = sum(f.units_expired + f.units_discarded for f in facts)
            if not total_in:
                return None
            return round(total_wasted / total_in * 100, 2)

        def _days_supply(cc):
            facts_30 = DemandFactDaily.objects.filter(
                branch=branch, component_class=cc,
                fact_date__lte=kpi_date,
            ).order_by('-fact_date')[:30]
            issued_30 = sum(f.units_issued for f in facts_30)
            avg_daily = issued_30 / 30 if issued_30 else 0
            current_stock = DemandFactDaily.objects.filter(
                branch=branch, component_class=cc, fact_date=kpi_date,
            ).values_list('closing_stock', flat=True).first() or 0
            if not avg_daily:
                return None
            return round(current_stock / avg_daily, 1)

        KpiDaily.objects.update_or_create(
            branch=branch,
            kpi_date=kpi_date,
            defaults=dict(
                ct_ratio_rbc=_ct('RBC'),
                ct_ratio_plt=_ct('PLT'),
                ct_ratio_ffp=_ct('FFP'),
                wastage_pct_rbc=_wastage('RBC'),
                wastage_pct_plt=_wastage('PLT'),
                days_supply_rbc=_days_supply('RBC'),
                days_supply_plt=_days_supply('PLT'),
                days_supply_ffp=_days_supply('FFP'),
            ),
        )

    def _run_forecast(self, branch, generated_on, optimise):
        for cc in COMPONENT_CLASSES:
            # Build the historical series — last 90 days of facts
            cutoff = generated_on - datetime.timedelta(days=90)
            facts = list(
                DemandFactDaily.objects.filter(
                    branch=branch, component_class=cc,
                    fact_date__gt=cutoff, fact_date__lte=generated_on,
                ).order_by('fact_date').values_list('units_issued', flat=True)
            )

            if len(facts) < 14:
                continue  # not enough history

            results = forecast_demand(
                series=[float(v) for v in facts],
                season_length=SEASON_LENGTH,
                n_ahead=FORECAST_HORIZON,
                optimise=optimise,
            )

            for h, (pred, lo, hi) in enumerate(results, start=1):
                horizon_date = generated_on + datetime.timedelta(days=h)
                Forecast.objects.update_or_create(
                    branch=branch,
                    component_class=cc,
                    generated_on=generated_on,
                    horizon_date=horizon_date,
                    defaults=dict(
                        predicted_units=pred,
                        lower_80=lo,
                        upper_80=hi,
                    ),
                )
