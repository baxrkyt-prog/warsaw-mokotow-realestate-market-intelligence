"""
analytics/lifecycle.py — Listing Lifecycle Intelligence.

Market flow: DOM (days on market), turnover, delisting velocity, stale listings,
lifecycle funnel, listing flow (new vs delisted).

DOM liczony od daty startu (published_date jeśli jest — realna data z Otodom,
inaczej first_seen) do delisted_date lub dziś. UDF dom_days w database.py.

Bucket DOM: 0-30 / 31-60 / 61-90 / 91-180 / 180+.
"""

from __future__ import annotations

import pandas as pd

from database import get_conn

# Próg "stale" = mediana DOM × 2, ale z sensownym minimum per typ
STALE_FLOOR = {"office": 180, "residential": 120}

DOM_BUCKETS = [(0, 30), (31, 60), (61, 90), (91, 180), (181, 10**9)]
DOM_BUCKET_LABELS = ["0-30", "31-60", "61-90", "91-180", "180+"]

# start DOM: realna data publikacji jeśli jest, inaczej first_seen
_DOM_START = "COALESCE(published_date, first_seen)"


def _asset_filter(asset_class: str | None):
    if asset_class == "office":
        return "asset_class='office'", {}
    if asset_class == "residential":
        return "asset_class='residential' AND transaction_type IN ('sale','invest_unit')", {}
    return "1=1", {}


def get_dom_stats(asset_class: str = "residential") -> dict:
    """Median/avg DOM + rozkład bucketów dla aktywnych ofert."""
    where, _ = _asset_filter(asset_class)
    with get_conn() as conn:
        df = pd.read_sql_query(f"""
            SELECT dom_days({_DOM_START}, NULL) AS dom
            FROM listings
            WHERE {where} AND is_active=1 AND {_DOM_START} IS NOT NULL
        """, conn)
    if df.empty or df["dom"].dropna().empty:
        return {"median_dom": None, "avg_dom": None, "n": 0,
                "buckets": {l: 0 for l in DOM_BUCKET_LABELS}, "real_dom": False}

    dom = df["dom"].dropna()
    buckets = {}
    for (lo, hi), label in zip(DOM_BUCKETS, DOM_BUCKET_LABELS):
        buckets[label] = int(((dom >= lo) & (dom <= hi)).sum())

    # czy DOM jest "realny" (oparty na published_date) czy dopiero się buduje
    with get_conn() as conn:
        pub = conn.execute(f"""
            SELECT COUNT(*) n, SUM(published_date IS NOT NULL) p
            FROM listings WHERE {where} AND is_active=1
        """).fetchone()
    real = bool(pub and pub["n"] and pub["p"] and pub["p"] / pub["n"] > 0.5)

    return {
        "median_dom": int(dom.median()),
        "avg_dom": int(dom.mean()),
        "n": int(len(dom)),
        "buckets": buckets,
        "real_dom": real,
    }


def get_turnover_rate(asset_class: str = "residential", window_days: int = 90) -> dict:
    """Turnover = delisted_w_oknie / aktywne_teraz. Zwraca 30/90/180 jeśli window=None."""
    where, _ = _asset_filter(asset_class)
    windows = [30, 90, 180] if window_days is None else [window_days]
    with get_conn() as conn:
        active = conn.execute(
            f"SELECT COUNT(*) c FROM listings WHERE {where} AND is_active=1"
        ).fetchone()["c"]
        out = {}
        for w in windows:
            delisted = conn.execute(f"""
                SELECT COUNT(*) c FROM listings
                WHERE {where} AND is_active=0 AND delisted_date >= date('now', '-{w} days')
            """).fetchone()["c"]
            out[w] = round(delisted / active * 100, 1) if active else None
    return {"active": active, "turnover_pct": out}


def get_delisting_kpis(asset_class: str = "residential") -> dict:
    where, _ = _asset_filter(asset_class)
    with get_conn() as conn:
        def cnt(days):
            return conn.execute(f"""
                SELECT COUNT(*) c FROM listings
                WHERE {where} AND is_active=0 AND delisted_date >= date('now','-{days} days')
            """).fetchone()["c"]
        d7, d30, d90 = cnt(7), cnt(30), cnt(90)
        d30_prev = conn.execute(f"""
            SELECT COUNT(*) c FROM listings
            WHERE {where} AND is_active=0
              AND delisted_date BETWEEN date('now','-60 days') AND date('now','-31 days')
        """).fetchone()["c"]
    velocity_delta = round((d30 - d30_prev) / d30_prev * 100, 1) if d30_prev else None
    return {"d7": d7, "d30": d30, "d90": d90,
            "velocity_per_day_30": round(d30 / 30, 2),
            "velocity_delta_pct": velocity_delta}


def get_delisting_trend(asset_class: str = "residential", bucket: str = "weekly",
                        days: int = 180) -> pd.DataFrame:
    where, _ = _asset_filter(asset_class)
    fmt = {"weekly": "%Y-W%W", "monthly": "%Y-%m",
           "quarterly": "%Y-Q"}.get(bucket, "%Y-%m")
    with get_conn() as conn:
        return pd.read_sql_query(f"""
            SELECT strftime('{fmt}', delisted_date) AS period, COUNT(*) AS delisted
            FROM listings
            WHERE {where} AND is_active=0 AND delisted_date >= date('now','-{days} days')
            GROUP BY period ORDER BY period
        """, conn)


def get_listing_flow(asset_class: str = "residential", days: int = 180,
                     bucket: str = "weekly") -> pd.DataFrame:
    """New vs Delisted w czasie — leading indicator kierunku rynku."""
    where, _ = _asset_filter(asset_class)
    fmt = {"weekly": "%Y-W%W", "monthly": "%Y-%m"}.get(bucket, "%Y-%m")
    with get_conn() as conn:
        new = pd.read_sql_query(f"""
            SELECT strftime('{fmt}', {_DOM_START}) AS period, COUNT(*) AS new_listings
            FROM listings
            WHERE {where} AND {_DOM_START} >= date('now','-{days} days')
            GROUP BY period
        """, conn)
        deli = pd.read_sql_query(f"""
            SELECT strftime('{fmt}', delisted_date) AS period, COUNT(*) AS delisted
            FROM listings
            WHERE {where} AND is_active=0 AND delisted_date >= date('now','-{days} days')
            GROUP BY period
        """, conn)
    if new.empty and deli.empty:
        return pd.DataFrame(columns=["period", "new_listings", "delisted"])
    df = new.merge(deli, on="period", how="outer").fillna(0).sort_values("period")
    df["new_listings"] = df["new_listings"].astype(int)
    df["delisted"] = df["delisted"].astype(int)
    df["net_flow"] = df["new_listings"] - df["delisted"]
    return df


def get_lifecycle_funnel(asset_class: str = "residential") -> dict:
    """Liczby na każdym etapie: NEW(30d) → ACTIVE → PRICE CHANGED → DELISTED."""
    where, _ = _asset_filter(asset_class)
    with get_conn() as conn:
        new30 = conn.execute(f"""
            SELECT COUNT(*) c FROM listings
            WHERE {where} AND {_DOM_START} >= date('now','-30 days')
        """).fetchone()["c"]
        active = conn.execute(f"SELECT COUNT(*) c FROM listings WHERE {where} AND is_active=1").fetchone()["c"]
        price_changed = conn.execute(f"""
            SELECT COUNT(*) c FROM listings
            WHERE {where} AND is_active=1 AND listing_status IN ('PRICE_REDUCED','PRICE_INCREASED')
        """).fetchone()["c"]
        delisted = conn.execute(f"SELECT COUNT(*) c FROM listings WHERE {where} AND is_active=0").fetchone()["c"]
    return {"NEW": new30, "ACTIVE": active, "PRICE_CHANGED": price_changed, "DELISTED": delisted}


def get_stale_listings(asset_class: str = "residential", limit: int = 100) -> pd.DataFrame:
    """Oferty starsze niż 2× mediana DOM (z floor per typ). Aktywne."""
    where, _ = _asset_filter(asset_class)
    stats = get_dom_stats(asset_class)
    median = stats["median_dom"] or 0
    threshold = max(median * 2, STALE_FLOOR.get(asset_class, 120))
    with get_conn() as conn:
        df = pd.read_sql_query(f"""
            SELECT offer_id, title, url, building_name, parent_project_id,
                   subdistrict, price_total, price_per_m2, listing_status,
                   dom_days({_DOM_START}, NULL) AS dom,
                   (SELECT COUNT(*) FROM listing_lifecycle_events e
                    WHERE e.offer_id=listings.offer_id
                      AND e.event_type IN ('PRICE_REDUCED','PRICE_INCREASED')) AS price_changes
            FROM listings
            WHERE {where} AND is_active=1 AND {_DOM_START} IS NOT NULL
              AND dom_days({_DOM_START}, NULL) >= {threshold}
            ORDER BY dom DESC
            LIMIT {limit}
        """, conn)
    return df


def get_lifecycle_kpis(asset_class: str = "residential") -> dict:
    """Zbiorczy zestaw KPI dla strony Lifecycle."""
    where, _ = _asset_filter(asset_class)
    dom = get_dom_stats(asset_class)
    turn = get_turnover_rate(asset_class, window_days=None)
    funnel = get_lifecycle_funnel(asset_class)
    with get_conn() as conn:
        new30 = funnel["NEW"]
        delisted30 = conn.execute(f"""
            SELECT COUNT(*) c FROM listings
            WHERE {where} AND is_active=0 AND delisted_date >= date('now','-30 days')
        """).fetchone()["c"]
    return {
        "new_30d": new30,
        "active": funnel["ACTIVE"],
        "delisted_30d": delisted30,
        "median_dom": dom["median_dom"],
        "real_dom": dom["real_dom"],
        "turnover_90d": turn["turnover_pct"].get(90),
    }
