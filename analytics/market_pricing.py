"""
analytics/market_pricing.py — Market Liquidity & Pricing.

Zastępuje stary moduł "Ceny Transakcyjne" oparty na danych demo/RCN.
Cała logika bazuje WYŁĄCZNIE na danych OFERTOWYCH (listings, wiele źródeł).

Kluczowa zmiana filozofii: zamiast udawać że mamy ceny transakcyjne,
ESTYMUJEMY je z cen ofertowych przez parametryzowany Discount Factor.

  Estimated Transaction Price = Median Asking Price × Discount Factor   (domyślnie 0.95)

Sekcje: Market Overview, Liquidity (absorption, ekspozycja, age buckets),
Estimated Transaction Price, Segmentacja (typ + metraż), Price Dynamics.
"""

from __future__ import annotations

import pandas as pd

from database import get_conn

DEFAULT_DISCOUNT_FACTOR = 0.95

AREA_BUCKETS = [(0, 40), (40, 60), (60, 80), (80, 120), (120, 10**9)]
AREA_BUCKET_LABELS = ["0–40", "40–60", "60–80", "80–120", "120+"]

# property_type w listings: residential(sale/invest_unit) + office(rent).
# retail/magazyny — przygotowane na przyszłe źródła (puste dopóki nie scrapujemy).
SEGMENTS = {
    "all":         "1=1",
    "residential": "asset_class='residential' AND transaction_type IN ('sale','invest_unit')",
    "office":      "asset_class='office'",
    "retail":      "asset_class='retail'",
    "warehouse":   "asset_class='warehouse'",
}

_DOM_START = "COALESCE(published_date, first_seen)"


def _seg_where(segment: str) -> str:
    return SEGMENTS.get(segment, "1=1")


# ──────────────────────────────────────────────
# SEKCJA 1 — MARKET OVERVIEW
# ──────────────────────────────────────────────

def get_market_overview(segment: str = "all") -> dict:
    where = _seg_where(segment)
    with get_conn() as conn:
        active = pd.read_sql_query(f"""
            SELECT price_total, price_per_m2 FROM listings
            WHERE {where} AND is_active=1 AND price_total IS NOT NULL
        """, conn)
        counts = conn.execute(f"""
            SELECT
                SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN {_DOM_START} >= date('now','-7 days') THEN 1 ELSE 0 END) AS new_7,
                SUM(CASE WHEN {_DOM_START} >= date('now','-30 days') THEN 1 ELSE 0 END) AS new_30,
                SUM(CASE WHEN is_active=0 AND delisted_date >= date('now','-7 days') THEN 1 ELSE 0 END) AS del_7,
                SUM(CASE WHEN is_active=0 AND delisted_date >= date('now','-30 days') THEN 1 ELSE 0 END) AS del_30
            FROM listings WHERE {where}
        """).fetchone()

    def stat(series):
        s = series.dropna()
        return (round(s.mean()), round(s.median())) if len(s) else (None, None)
    avg_p, med_p = stat(active["price_total"]) if not active.empty else (None, None)
    avg_m2, med_m2 = stat(active["price_per_m2"]) if not active.empty else (None, None)

    return {
        "active": counts["active"] or 0,
        "new_7": counts["new_7"] or 0, "new_30": counts["new_30"] or 0,
        "delisted_7": counts["del_7"] or 0, "delisted_30": counts["del_30"] or 0,
        "avg_price": avg_p, "median_price": med_p,
        "avg_price_m2": avg_m2, "median_price_m2": med_m2,
    }


# ──────────────────────────────────────────────
# SEKCJA 2 — MARKET LIQUIDITY
# ──────────────────────────────────────────────

def get_market_liquidity(segment: str = "all", window_days: int = 30) -> dict:
    """Absorption Rate = delisted/new; czas ekspozycji (DOM); oferty starsze niż progi."""
    where = _seg_where(segment)
    with get_conn() as conn:
        flow = conn.execute(f"""
            SELECT
                SUM(CASE WHEN {_DOM_START} >= date('now','-{window_days} days') THEN 1 ELSE 0 END) AS new_w,
                SUM(CASE WHEN is_active=0 AND delisted_date >= date('now','-{window_days} days') THEN 1 ELSE 0 END) AS del_w
            FROM listings WHERE {where}
        """).fetchone()
        exposure = pd.read_sql_query(f"""
            SELECT dom_days(published_date, NULL) AS dom FROM listings
            WHERE {where} AND is_active=1 AND published_date IS NOT NULL
        """, conn)

    new_w = flow["new_w"] or 0
    del_w = flow["del_w"] or 0
    absorption = round(del_w / new_w * 100, 1) if new_w else None

    dom = exposure["dom"].dropna()
    older = {f"{t}d": int((dom > t).sum()) for t in (30, 60, 90, 180)} if len(dom) else {}

    return {
        "absorption_rate": absorption, "new_w": new_w, "delisted_w": del_w,
        "avg_exposure": int(dom.mean()) if len(dom) else None,
        "median_exposure": int(dom.median()) if len(dom) else None,
        "older_than": older, "window_days": window_days,
    }


# ──────────────────────────────────────────────
# SEKCJA 3 — DELISTED per dzielnica
# ──────────────────────────────────────────────

def get_delisted_by_district(segment: str = "all") -> pd.DataFrame:
    where = _seg_where(segment)
    with get_conn() as conn:
        # Scalamy warianty pisowni: district_norm albo normalize_district_sql(subdistrict).
        # Alias NIE 'district' (kolizja z kolumną listings.district).
        df = pd.read_sql_query(f"""
            SELECT COALESCE(gd.display_name,
                            COALESCE(l.district_norm, normalize_district_sql(l.subdistrict)),
                            l.subdistrict, '(nieznana)') AS district_label,
                   SUM(CASE WHEN l.is_active=0 AND l.delisted_date >= date('now','-7 days') THEN 1 ELSE 0 END) AS d7,
                   SUM(CASE WHEN l.is_active=0 AND l.delisted_date >= date('now','-30 days') THEN 1 ELSE 0 END) AS d30,
                   SUM(CASE WHEN l.is_active=0 AND l.delisted_date >= date('now','-90 days') THEN 1 ELSE 0 END) AS d90,
                   SUM(CASE WHEN l.is_active=1 THEN 1 ELSE 0 END) AS active
            FROM listings l
            LEFT JOIN geo_districts gd
                ON gd.district_norm = COALESCE(l.district_norm, normalize_district_sql(l.subdistrict))
            WHERE {where}
            GROUP BY 1
            HAVING active > 0 OR d90 > 0
            ORDER BY d30 DESC
        """, conn)
    return df


# ──────────────────────────────────────────────
# SEKCJA 4 — ESTIMATED TRANSACTION PRICE
# ──────────────────────────────────────────────

def estimate_transaction_price(segment: str = "all",
                               discount_factor: float = DEFAULT_DISCOUNT_FACTOR) -> dict:
    """Estymowana cena transakcyjna = mediana ceny ofertowej × discount factor.
    Parametryzowany; w przyszłości kalibrowany na realnych danych."""
    ov = get_market_overview(segment)
    med_total = ov["median_price"]
    med_m2 = ov["median_price_m2"]
    return {
        "discount_factor": discount_factor,
        "median_asking": med_total,
        "median_asking_m2": med_m2,
        "est_transaction": round(med_total * discount_factor) if med_total else None,
        "est_transaction_m2": round(med_m2 * discount_factor) if med_m2 else None,
        "implied_negotiation_pct": round((discount_factor - 1) * 100, 1),
    }


# ──────────────────────────────────────────────
# SEKCJA 5 — SEGMENTATION (typ + metraż)
# ──────────────────────────────────────────────

def get_segmentation(discount_factor: float = DEFAULT_DISCOUNT_FACTOR) -> dict:
    """Metryki dla każdego segmentu typu + przedziałów metrażu."""
    by_type = []
    for seg in ("all", "residential", "office", "retail", "warehouse"):
        ov = get_market_overview(seg)
        est = estimate_transaction_price(seg, discount_factor)
        by_type.append({
            "segment": seg, "active": ov["active"],
            "median_m2": ov["median_price_m2"],
            "est_transaction_m2": est["est_transaction_m2"],
        })

    # metraż — w obrębie residential (najsensowniejszy)
    by_area = []
    with get_conn() as conn:
        for (lo, hi), label in zip(AREA_BUCKETS, AREA_BUCKET_LABELS):
            row = pd.read_sql_query(f"""
                SELECT price_per_m2 FROM listings
                WHERE {SEGMENTS['residential']} AND is_active=1
                  AND area_m2 >= {lo} AND area_m2 < {hi} AND price_per_m2 IS NOT NULL
            """, conn)
            n = len(row)
            med = round(row["price_per_m2"].median()) if n else None
            by_area.append({
                "bucket": label, "active": n, "median_m2": med,
                "est_transaction_m2": round(med * discount_factor) if med else None,
            })
    return {"by_type": pd.DataFrame(by_type), "by_area": pd.DataFrame(by_area)}


# ──────────────────────────────────────────────
# SEKCJA 6 — PRICE DYNAMICS
# ──────────────────────────────────────────────

def get_price_dynamics(segment: str = "all") -> dict:
    """Zmiana mediany i średniej ceny/m² dla 7/30/90 dni (ze snapshotów)."""
    # mapowanie segmentu na join warunki snapshotów
    join_where = {
        "all": "1=1",
        "residential": "l.asset_class='residential' AND l.transaction_type IN ('sale','invest_unit')",
        "office": "l.asset_class='office'",
        "retail": "l.asset_class='retail'",
        "warehouse": "l.asset_class='warehouse'",
    }.get(segment, "1=1")

    def window_stats(days_from, days_to):
        with get_conn() as conn:
            return conn.execute(f"""
                SELECT AVG(s.current_price_m2) avg_m2,
                       COUNT(s.current_price_m2) n
                FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
                WHERE {join_where} AND s.active_status=1 AND s.current_price_m2 IS NOT NULL
                  AND s.scrape_date BETWEEN date('now','-{days_to} days') AND date('now','-{days_from} days')
            """).fetchone()

    def median_window(days_from, days_to):
        with get_conn() as conn:
            df = pd.read_sql_query(f"""
                SELECT s.current_price_m2 v FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
                WHERE {join_where} AND s.active_status=1 AND s.current_price_m2 IS NOT NULL
                  AND s.scrape_date BETWEEN date('now','-{days_to} days') AND date('now','-{days_from} days')
            """, conn)
        return df["v"].median() if not df.empty else None

    out = {}
    now_avg = window_stats(0, 1)["avg_m2"]
    now_med = median_window(0, 1)
    for w in (7, 30, 90):
        prev_avg = window_stats(w, w + 1)["avg_m2"]
        prev_med = median_window(w, w + 1)
        out[f"{w}d"] = {
            "avg_chg": round((now_avg - prev_avg) / prev_avg * 100, 1) if (now_avg and prev_avg) else None,
            "median_chg": round((now_med - prev_med) / prev_med * 100, 1) if (now_med and prev_med) else None,
        }
    return out


# ──────────────────────────────────────────────
# SEKCJA 8 — composite KPI (top dashboardu)
# ──────────────────────────────────────────────

def get_market_kpis(segment: str = "all",
                    discount_factor: float = DEFAULT_DISCOUNT_FACTOR) -> dict:
    ov = get_market_overview(segment)
    liq = get_market_liquidity(segment, 30)
    est = estimate_transaction_price(segment, discount_factor)
    from .lifecycle import get_dom_stats
    dom_ac = segment if segment in ("office", "residential") else "residential"
    dom = get_dom_stats(dom_ac)
    return {
        "active": ov["active"],
        "new_30": ov["new_30"],
        "delisted_30": ov["delisted_30"],
        "absorption_rate": liq["absorption_rate"],
        "median_price_m2": ov["median_price_m2"],
        "est_transaction_m2": est["est_transaction_m2"],
        "median_listing_age": dom["median_dom"],
        "discount_factor": discount_factor,
    }
