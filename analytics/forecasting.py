"""
Holt-Winters additive triple exponential smoothing.
Pure Python — no paid libraries. Uses only the standard library.

Reference: Chatfield (2000), The Analysis of Time Series.
"""
from math import sqrt


def _holt_winters_additive(series, season_length, n_ahead,
                           alpha=0.3, beta=0.1, gamma=0.3):
    """
    Fit Holt-Winters additive model and return (fitted, forecast, sse).

    series        — list of observed values (≥ 2 full seasons recommended)
    season_length — periodicity (7 for weekly seasonality)
    n_ahead       — number of future steps to forecast
    alpha         — level smoothing (0–1)
    beta          — trend smoothing (0–1)
    gamma         — seasonal smoothing (0–1)
    """
    m = season_length
    n = len(series)
    if n < 2 * m:
        # Insufficient history — fall back to simple mean
        mean = sum(series) / n if n else 0.0
        return [], [max(0.0, mean)] * n_ahead, 0.0

    # Initial estimates
    level = sum(series[:m]) / m
    trend = (sum(series[m:2*m]) - sum(series[:m])) / (m * m)
    seasonals = [series[i] - level for i in range(m)]

    fitted = []
    sse = 0.0

    for i in range(n):
        if i == 0:
            fitted.append(level + trend + seasonals[0])
            continue
        prev_level = level
        prev_trend = trend
        obs = series[i]
        seasonal_idx = i % m
        hat = prev_level + prev_trend + seasonals[seasonal_idx]
        fitted.append(hat)
        err = obs - hat
        sse += err ** 2
        level = alpha * (obs - seasonals[seasonal_idx]) + (1 - alpha) * (prev_level + prev_trend)
        trend = beta * (level - prev_level) + (1 - beta) * prev_trend
        seasonals[seasonal_idx] = gamma * (obs - level) + (1 - gamma) * seasonals[seasonal_idx]

    forecast = []
    rmse = sqrt(sse / max(n - 1, 1))
    for h in range(1, n_ahead + 1):
        idx = (n - 1 + h) % m
        f = level + h * trend + seasonals[idx]
        forecast.append(max(0.0, round(f, 2)))

    return fitted, forecast, rmse


def _optimise_params(series, season_length):
    """
    Grid search over alpha/beta/gamma to minimise SSE.
    Returns best (alpha, beta, gamma, rmse).
    """
    best = (0.3, 0.1, 0.3, float('inf'))
    for a in (0.1, 0.2, 0.3, 0.4, 0.5, 0.7):
        for b in (0.05, 0.1, 0.2, 0.3):
            for g in (0.1, 0.2, 0.3, 0.4, 0.5):
                _, _, sse = _holt_winters_additive(series, season_length, 0, a, b, g)
                if sse < best[3]:
                    best = (a, b, g, sse)
    return best


def forecast_demand(series, season_length=7, n_ahead=14, optimise=False):
    """
    Public entry point. Returns a list of (predicted, lower_80, upper_80) for n_ahead days.

    series        — list of floats: daily demand history, oldest first
    season_length — 7 for weekly
    n_ahead       — days to forecast
    optimise      — run grid search to tune smoothing params (slower)
    """
    if not series:
        return [(0.0, 0.0, 0.0)] * n_ahead

    if optimise:
        alpha, beta, gamma, _ = _optimise_params(series, season_length)
    else:
        alpha, beta, gamma = 0.3, 0.1, 0.3

    _, point_forecasts, rmse = _holt_winters_additive(
        series, season_length, n_ahead, alpha, beta, gamma,
    )

    z80 = 1.282  # 80% prediction interval
    results = []
    for h, pf in enumerate(point_forecasts, start=1):
        half = z80 * rmse * sqrt(h)
        results.append((
            round(pf, 2),
            round(max(0.0, pf - half), 2),
            round(pf + half, 2),
        ))
    return results
