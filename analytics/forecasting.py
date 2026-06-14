"""
analytics/forecasting.py — prognozy trendu (regresja liniowa + 95% CI).
"""

import pandas as pd
import numpy as np
from scipy import stats as scipy_stats

from .listings import get_office_trend, get_residential_trend


def forecast_trend(df: pd.DataFrame, date_col: str, value_col: str, horizon_days: int = 30) -> pd.DataFrame:
    """Liniowy trend + przedział ufności 95%."""
    if df.empty or value_col not in df.columns:
        return pd.DataFrame()
    df = df.dropna(subset=[date_col, value_col]).copy()
    if len(df) < 3:
        return pd.DataFrame()

    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    x = (df[date_col] - df[date_col].min()).dt.days.values
    y = df[value_col].values

    slope, intercept, _, _, _ = scipy_stats.linregress(x, y)
    last_day = x[-1]
    future_x = np.arange(last_day + 1, last_day + horizon_days + 1)
    future_dates = df[date_col].max() + pd.to_timedelta(future_x - last_day, unit="D")

    forecast = intercept + slope * future_x
    residuals = y - (intercept + slope * x)
    rmse = float(np.sqrt(np.mean(residuals ** 2)))

    return pd.DataFrame({
        "date": future_dates,
        "forecast": forecast,
        "lower": forecast - 1.96 * rmse,
        "upper": forecast + 1.96 * rmse,
    })


def get_office_forecast(days: int = 90, horizon: int = 30) -> tuple:
    hist = get_office_trend(days)
    fcast = forecast_trend(hist, "scrape_date", "avg_price_m2", horizon) if not hist.empty else pd.DataFrame()
    return hist, fcast


def get_residential_forecast(days: int = 90, horizon: int = 30) -> tuple:
    hist = get_residential_trend(days)
    fcast = forecast_trend(hist, "scrape_date", "avg_price_m2", horizon) if not hist.empty else pd.DataFrame()
    return hist, fcast
