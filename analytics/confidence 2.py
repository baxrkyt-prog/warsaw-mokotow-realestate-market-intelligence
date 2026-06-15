"""
analytics/confidence.py — model ufności danych transakcyjnych + winsoryzacja.

Reguły (dokumentacja modelu — używana w UI jako tooltip):

  HIGH    — n ≥ 30 obserwacji ORAZ najmłodsza obserwacja ≤ 90 dni
  MEDIUM  — n ≥ 10
  LOW     — n ≥ 3
  SUPPRESS — n < 3 → wartości NIE wolno pokazywać (mediana z 2 transakcji
             to nie mediana rynku; UI pokazuje "n/d")

Winsoryzacja: zawsze przed medianą/średnią cen transakcyjnych — obcina
percentyle 1/99 (darowizny rodzinne, błędy wpisu, transakcje wewnątrzgrupowe).
"""

from __future__ import annotations

import pandas as pd

HIGH = "high"
MEDIUM = "medium"
LOW = "low"
SUPPRESS = "suppress"

# Kolejność do porównań (wyższy indeks = lepiej)
_ORDER = [SUPPRESS, LOW, MEDIUM, HIGH]


def confidence_level(n: int, data_age_days: int | None = None) -> str:
    """Poziom ufności agregatu z n obserwacji; data_age_days = wiek najmłodszej."""
    if n is None or n < 3:
        return SUPPRESS
    if n >= 30 and (data_age_days is None or data_age_days <= 90):
        return HIGH
    if n >= 10:
        return MEDIUM
    return LOW


def worst_of(*levels: str) -> str:
    """Najgorszy z poziomów (do łączenia metryk składowych)."""
    return min(levels, key=lambda l: _ORDER.index(l) if l in _ORDER else 0)


def is_displayable(level: str) -> bool:
    return level != SUPPRESS


def winsorize(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """Obcina wartości poza percentylami [lower, upper]. Bezpieczne dla małych n."""
    s = series.dropna()
    if len(s) < 5:
        return s  # za mało obserwacji żeby sensownie obcinać
    lo, hi = s.quantile(lower), s.quantile(upper)
    return s.clip(lo, hi)


def winsorized_median(series: pd.Series) -> float | None:
    s = winsorize(series)
    return float(s.median()) if len(s) else None


def winsorized_mean(series: pd.Series) -> float | None:
    s = winsorize(series)
    return float(s.mean()) if len(s) else None
