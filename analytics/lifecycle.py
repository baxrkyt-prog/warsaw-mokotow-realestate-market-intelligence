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
    """Median/avg DOM + buckety dla aktywnych ofert.

    DOM liczony WYŁĄCZNIE z published_date (realna data publikacji). first_seen NIE
    jest używany jako fallback — dla oferty pobranej dziś first_seen=dziś, co
    zaniżałoby DOM do ~0 (oferta może mieć miesiące). Oferty bez published_date
    (np. Morizon) są wykluczone z DOM — nie znamy ich realnego wieku.
    """
    where, _ = _asset_filter(asset_class)
    with get_conn() as conn:
        df = pd.read_sql_query(f"""
            SELECT dom_days(published_date, NULL) AS dom
            FROM listings
            WHERE {where} AND is_active=1 AND published_date IS NOT NULL
        """, conn)
        total = conn.execute(
            f"SELECT COUNT(*) c FROM listings WHERE {where} AND is_active=1").fetchone()["c"]

    if df.empty or df["dom"].dropna().empty:
        return {"median_dom": None, "avg_dom": None, "n": 0, "coverage_pct": 0,
                "buckets": {l: 0 for l in DOM_BUCKET_LABELS}, "real_dom": False}

    dom = df["dom"].dropna()
    buckets = {}
    for (lo, hi), label in zip(DOM_BUCKETS, DOM_BUCKET_LABELS):
        buckets[label] = int(((dom >= lo) & (dom <= hi)).sum())
    coverage = round(len(dom) / total * 100) if total else 0

    return {
        "median_dom": int(dom.median()),
        "avg_dom": int(dom.mean()),
        "n": int(len(dom)),
        "coverage_pct": coverage,      # % aktywnych ofert ze znaną datą publikacji
        "buckets": buckets,
        "real_dom": len(dom) >= 10,    # wystarczająco dużo ofert ze znaną datą
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
        # Potwierdzony delisting (delisted_date) — bez artefaktów one-shot/cold-start
        delisted = conn.execute(
            f"SELECT COUNT(*) c FROM listings WHERE {where} AND delisted_date >= date('now','-30 days')"
        ).fetchone()["c"]
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
                   dom_days(published_date, NULL) AS dom,
                   (SELECT COUNT(*) FROM listing_lifecycle_events e
                    WHERE e.offer_id=listings.offer_id
                      AND e.event_type IN ('PRICE_REDUCED','PRICE_INCREASED')) AS price_changes
            FROM listings
            WHERE {where} AND is_active=1 AND published_date IS NOT NULL
              AND dom_days(published_date, NULL) >= {threshold}
            ORDER BY dom DESC
            LIMIT {limit}
        """, conn)
    return df


def record_lifecycle_snapshot(snapshot_date: str | None = None) -> dict:
    """Zapisuje dzienny snapshot median DOM / turnover / stale per asset_class.
    Baza porównawcza dla alertów lifecycle. Idempotentny (PK date+asset)."""
    from datetime import datetime, timezone
    snapshot_date = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    out = {}
    with get_conn() as conn:
        for ac in ("office", "residential"):
            dom = get_dom_stats(ac)
            turn = get_turnover_rate(ac, window_days=30)["turnover_pct"].get(30)
            stale = len(get_stale_listings(ac, limit=10000))
            where, _ = _asset_filter(ac)
            active = conn.execute(f"SELECT COUNT(*) c FROM listings WHERE {where} AND is_active=1").fetchone()["c"]
            conn.execute("""
                INSERT OR REPLACE INTO lifecycle_snapshots
                    (snapshot_date, asset_class, median_dom, turnover_pct, stale_count, active)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (snapshot_date, ac, dom["median_dom"], turn, stale, active))
            out[ac] = {"median_dom": dom["median_dom"], "turnover": turn,
                       "stale": stale, "active": active}
    return out


def get_building_lifecycle() -> pd.DataFrame:
    """Per budynek biurowy: median DOM (aktywne), nowe 30d, delisted 30d, turnover."""
    from database import COMPETITIVE_SET
    with get_conn() as conn:
        active = pd.read_sql_query(f"""
            SELECT building_name,
                   dom_days(published_date, NULL) AS dom
            FROM listings
            WHERE asset_class='office' AND is_active=1 AND building_name IS NOT NULL
              AND published_date IS NOT NULL
        """, conn)
        flow = pd.read_sql_query(f"""
            SELECT building_name,
                   SUM(CASE WHEN {_DOM_START} >= date('now','-30 days') THEN 1 ELSE 0 END) AS new_30,
                   SUM(CASE WHEN is_active=0 AND delisted_date >= date('now','-30 days') THEN 1 ELSE 0 END) AS delisted_30,
                   SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active
            FROM listings
            WHERE asset_class='office' AND building_name IS NOT NULL
            GROUP BY building_name
        """, conn)

    if flow.empty:
        return pd.DataFrame()

    # mapowanie na competitive set
    def to_comp(name):
        nl = (name or "").lower()
        for bname, kws in COMPETITIVE_SET.items():
            if any(kw in nl for kw in kws):
                return bname
        return None

    flow["building"] = flow["building_name"].apply(to_comp)
    flow = flow[flow["building"].notna()]
    if flow.empty:
        return pd.DataFrame()

    med = active.copy()
    med["building"] = med["building_name"].apply(to_comp)
    med = med[med["building"].notna()]
    med_dom = med.groupby("building")["dom"].median().rename("median_dom")

    agg = flow.groupby("building").agg(
        new_30=("new_30", "sum"),
        delisted_30=("delisted_30", "sum"),
        active=("active", "sum"),
    ).reset_index().merge(med_dom, on="building", how="left")
    agg["turnover_pct"] = (agg["delisted_30"] / agg["active"].clip(lower=1) * 100).round(1)
    agg["median_dom"] = agg["median_dom"].round(0)
    return agg.sort_values("median_dom")


def get_project_lifecycle(project_id: str) -> dict:
    """Per projekt deweloperski: median DOM jednostek, nowe/delisted 30d, turnover."""
    with get_conn() as conn:
        med = conn.execute(f"""
            SELECT dom_days(published_date, NULL) AS dom FROM listings
            WHERE parent_project_id=? AND transaction_type='invest_unit'
              AND is_active=1 AND published_date IS NOT NULL
        """, (project_id,)).fetchall()
        flow = conn.execute(f"""
            SELECT
                SUM(CASE WHEN {_DOM_START} >= date('now','-30 days') THEN 1 ELSE 0 END) AS new_30,
                SUM(CASE WHEN is_active=0 AND delisted_date >= date('now','-30 days') THEN 1 ELSE 0 END) AS delisted_30,
                SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active
            FROM listings WHERE parent_project_id=? AND transaction_type='invest_unit'
        """, (project_id,)).fetchone()
    doms = sorted([r["dom"] for r in med if r["dom"] is not None])
    median_dom = doms[len(doms)//2] if doms else None
    active = flow["active"] or 0
    delisted_30 = flow["delisted_30"] or 0
    return {
        "median_dom": median_dom,
        "new_30": flow["new_30"] or 0,
        "delisted_30": delisted_30,
        "active": active,
        "turnover_pct": round(delisted_30 / max(active, 1) * 100, 1) if active else None,
    }


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
