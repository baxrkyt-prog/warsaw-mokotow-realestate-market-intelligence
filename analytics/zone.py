"""
analytics/zone.py — Ocean Plaza Zone Intelligence (strefy 500/1000/2000m).

Strefy liczone Haversine od OCEAN_PLAZA_LAT/LON (Domaniewska 50, zweryfikowane GUGiK).
Strefy są KUMULATYWNE (1000m zawiera 500m) — tak czyta się je naturalnie
w analizie nieruchomości ("w promieniu X od aktywa").
"""

from __future__ import annotations

import pandas as pd

from database import get_conn
from .confidence import confidence_level, winsorized_median, SUPPRESS

ZONES_M = [500, 1000, 2000]


def get_zone_intelligence(window_days: int = 180) -> pd.DataFrame:
    """Tabela stref: asking, transaction, spread, tx count, liquidity proxy, active listings.

    Zwraca DataFrame z wierszem per strefa. Wartości None gdy suppress.
    """
    rows = []
    with get_conn() as conn:
        for radius in ZONES_M:
            ask = pd.read_sql_query("""
                SELECT price_per_m2 FROM listings
                WHERE is_active=1 AND asset_class='residential'
                  AND transaction_type IN ('sale','invest_unit')
                  AND price_per_m2 IS NOT NULL AND latitude IS NOT NULL
                  AND ocean_plaza_dist_m(latitude, longitude) < :r
            """, conn, params={"r": radius})

            tx = pd.read_sql_query("""
                SELECT transaction_price_per_m2, transaction_date FROM transactions
                WHERE property_type='residential'
                  AND transaction_price_per_m2 IS NOT NULL AND latitude IS NOT NULL
                  AND transaction_date >= date('now', :w)
                  AND ocean_plaza_dist_m(latitude, longitude) < :r
            """, conn, params={"r": radius, "w": f"-{window_days} days"})

            office_active = conn.execute("""
                SELECT COUNT(*) c FROM listings
                WHERE is_active=1 AND asset_class='office'
                  AND latitude IS NOT NULL
                  AND ocean_plaza_dist_m(latitude, longitude) < ?
            """, (radius,)).fetchone()["c"]

            new_30 = conn.execute("""
                SELECT COUNT(*) c FROM listings
                WHERE asset_class='residential' AND transaction_type IN ('sale','invest_unit')
                  AND first_seen >= date('now','-30 days')
                  AND latitude IS NOT NULL
                  AND ocean_plaza_dist_m(latitude, longitude) < ?
            """, (radius,)).fetchone()["c"]

            n_ask, n_tx = len(ask), len(tx)
            med_ask = winsorized_median(ask["price_per_m2"]) if n_ask >= 3 else None
            conf = confidence_level(n_tx)
            med_tx = winsorized_median(tx["transaction_price_per_m2"]) if conf != SUPPRESS else None
            spread = ((med_tx - med_ask) / med_ask * 100) if (med_tx and med_ask) else None

            # Liquidity proxy strefowy: tx velocity vs nowa podaż (uproszczone — pełny
            # score wymaga okien porównawczych, na strefach próbka bywa za mała)
            tx_30 = len(tx[pd.to_datetime(tx["transaction_date"])
                           >= pd.Timestamp.now() - pd.Timedelta(days=30)]) if n_tx else 0
            if conf != SUPPRESS and (tx_30 + new_30) > 0:
                liq = round(min(100, (tx_30 / max(new_30, 1)) * 100))
            else:
                liq = None

            rows.append({
                "zone_m": radius,
                "zone_label": f"{radius} m",
                "median_asking": round(med_ask, 0) if med_ask else None,
                "median_transaction": round(med_tx, 0) if med_tx else None,
                "spread_pct": round(spread, 1) if spread is not None else None,
                "tx_count": n_tx,
                "liquidity": liq,
                "active_listings": n_ask,
                "office_listings": office_active,
                "confidence": conf,
            })
    return pd.DataFrame(rows)
