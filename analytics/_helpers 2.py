"""
analytics/_helpers.py — wspólne helpery używane przez submoduły.
"""


def mom_delta(curr, prev):
    """Procentowa zmiana okres-do-okresu, zaokrąglona do 1 m.d.; None jeśli brak danych."""
    if curr is not None and prev is not None and prev > 0:
        return round((curr - prev) / prev * 100, 1)
    return None
