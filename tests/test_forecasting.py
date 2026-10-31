"""
Unit tests for the Holt-Winters demand forecasting engine.

Run with: python manage.py test tests.test_forecasting
"""
from django.test import SimpleTestCase
from analytics.forecasting import _holt_winters_additive, forecast_demand


class HoltWintersTests(SimpleTestCase):

    def test_insufficient_history_returns_mean(self):
        series = [5.0] * 6  # less than 2 seasons of 7
        _, forecast, _ = _holt_winters_additive(series, season_length=7, n_ahead=3)
        self.assertEqual(len(forecast), 3)
        for v in forecast:
            self.assertAlmostEqual(v, 5.0, places=1)

    def test_forecast_length(self):
        series = list(range(1, 50))
        _, forecast, _ = _holt_winters_additive(series, season_length=7, n_ahead=14)
        self.assertEqual(len(forecast), 14)

    def test_no_negative_forecasts(self):
        series = [max(0, 10 + i % 3 - 5) for i in range(60)]
        _, forecast, _ = _holt_winters_additive(series, season_length=7, n_ahead=14)
        for v in forecast:
            self.assertGreaterEqual(v, 0.0, "Forecasts should never be negative")

    def test_constant_series_forecast_is_constant(self):
        series = [10.0] * 30
        _, forecast, _ = _holt_winters_additive(series, season_length=7, n_ahead=7)
        for v in forecast:
            self.assertAlmostEqual(v, 10.0, delta=2.0)

    def test_forecast_demand_public_api(self):
        series = [5 + (i % 7) for i in range(60)]
        results = forecast_demand(series, season_length=7, n_ahead=7)
        self.assertEqual(len(results), 7)
        for pred, lo, hi in results:
            self.assertGreaterEqual(pred, 0)
            self.assertLessEqual(lo, pred)
            self.assertGreaterEqual(hi, pred)

    def test_empty_series_returns_zeros(self):
        results = forecast_demand([], n_ahead=5)
        self.assertEqual(len(results), 5)
        for pred, lo, hi in results:
            self.assertEqual(pred, 0.0)
