"""
analytics/transactions.py — Transaction Intelligence Layer.
KPI / agregaty na tabeli `transactions`.

Phase 1: surowe metryki bez confidence/winsorize (te dochodzą w Fazie 4).
"""

from __future__ import annotations

import pandas as pd

from database import get_conn


def _pt_clause(property_type: str | None) -> tuple[str, dict]:
    if property_type:
        return "AND property_type = :pt", {"pt": property_type}
    return "", {}


def _dn_clause(district_norm: str | None) -> tuple[str, dict]:
    if district_norm:
        return "AND district_norm = :dn", {"dn": district_norm}
    return "", {}


def get_transaction_kpis(
    property_type: str | None = None,
    district_norm: str | None = None,
    window_days: int = 90,
) -> dict:
    """KPI bieżące + okres poprzedni dla delty."""
    pt_sql, pt_p = _pt_clause(property_type)
    dn_sql, dn_p = _dn_clause(district_norm)
    params = {"days": f"-{window_days} days",
              "prev_start": f"-{window_days * 2} days",
              "prev_end":   f"-{window_days + 1} days",
              **pt_p, **dn_p}

    sql_curr = f"""
        SELECT
            COUNT(*) as n,
            AVG(transaction_price_per_m2)    as avg_p,
            SUM(transaction_price)           as volume,
            MIN(transaction_price_per_m2)    as min_p,
            MAX(transaction_price_per_m2)    as max_p
        FROM transactions
        WHERE transaction_date >= date('now', :days)
          {pt_sql} {dn_sql}
    """
    sql_med = f"""
        SELECT transaction_price_per_m2 as v FROM transactions
        WHERE transaction_date >= date('now', :days)
          {pt_sql} {dn_sql}
          AND transaction_price_per_m2 IS NOT NULL
        ORDER BY transaction_price_per_m2
        LIMIT 1 OFFSET (
            SELECT COUNT(*)/2 FROM transactions
            WHERE transaction_date >= date('now', :days)
              {pt_sql} {dn_sql}
              AND transaction_price_per_m2 IS NOT NULL
        )
    """
    sql_prev = f"""
        SELECT
            COUNT(*) as n,
            AVG(transaction_price_per_m2) as avg_p,
            SUM(transaction_price)        as volume
        FROM transactions
        WHERE transaction_date BETWEEN date('now', :prev_start) AND date('now', :prev_end)
          {pt_sql} {dn_sql}
    """

    with get_conn() as conn:
        curr = conn.execute(sql_curr, params).fetchone()
        med  = conn.execute(sql_med,  params).fetchone()
        prev = conn.execute(sql_prev, params).fetchone()

    def pct(c, p):
        if c is None or p is None or not p:
            return None
        return round((c - p) / p * 100, 1)

    n = curr["n"] or 0
    avg_p = curr["avg_p"]
    median_p = med["v"] if med else None
    volume = curr["volume"] or 0
    return {
        "median_price_per_m2":  round(median_p, 0) if median_p else None,
        "average_price_per_m2": round(avg_p, 0) if avg_p else None,
        "transaction_count":    n,
        "transaction_volume":   round(volume, 0),
        "min_price_per_m2":     round(curr["min_p"], 0) if curr["min_p"] else None,
        "max_price_per_m2":     round(curr["max_p"], 0) if curr["max_p"] else None,
        "deltas": {
            "transaction_count":    pct(n, prev["n"]),
            "average_price_per_m2": pct(avg_p, prev["avg_p"]),
            "transaction_volume":   pct(volume, prev["volume"]),
        },
        "window_days": window_days,
        "property_type": property_type,
        "district_norm": district_norm,
    }


def get_transaction_trend(
    property_type: str | None = None,
    district_norm: str | None = None,
    days: int = 365,
    bucket: str = "monthly",
) -> pd.DataFrame:
    """Time-series: data_bucket | median | mean | count | volume."""
    pt_sql, pt_p = _pt_clause(property_type)
    dn_sql, dn_p = _dn_clause(district_norm)
    params = {"days": f"-{days} days", **pt_p, **dn_p}

    bucket_expr = {
        "daily":     "transaction_date",
        "weekly":    "strftime('%Y-W%W', transaction_date)",
        "monthly":   "strftime('%Y-%m', transaction_date)",
        "quarterly": "strftime('%Y-Q', transaction_date) || ((CAST(strftime('%m', transaction_date) AS INTEGER)-1)/3 + 1)",
    }.get(bucket, "strftime('%Y-%m', transaction_date)")

    sql = f"""
        SELECT
            {bucket_expr} as date_bucket,
            AVG(transaction_price_per_m2) as mean_p,
            COUNT(*) as cnt,
            SUM(transaction_price) as volume
        FROM transactions
        WHERE transaction_date >= date('now', :days)
          AND transaction_price_per_m2 IS NOT NULL
          {pt_sql} {dn_sql}
        GROUP BY date_bucket
        ORDER BY date_bucket
    """
    with get_conn() as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    # Mediana per bucket — łatwiej w pandas (SQLite nie ma natywnej median)
    if not df.empty:
        with get_conn() as conn:
            raw = pd.read_sql_query(f"""
                SELECT {bucket_expr} as date_bucket, transaction_price_per_m2 as v
                FROM transactions
                WHERE transaction_date >= date('now', :days)
                  AND transaction_price_per_m2 IS NOT NULL
                  {pt_sql} {dn_sql}
            """, conn, params=params)
        med = raw.groupby("date_bucket")["v"].median().rename("median_p")
        df = df.merge(med, on="date_bucket", how="left")
        df = df[["date_bucket", "median_p", "mean_p", "cnt", "volume"]]
    return df


def get_transaction_geography(
    property_type: str | None = None,
    window_days: int = 90,
) -> pd.DataFrame:
    """Per district_norm: count, median, mean, volume."""
    pt_sql, pt_p = _pt_clause(property_type)
    params = {"days": f"-{window_days} days", **pt_p}
    with get_conn() as conn:
        df = pd.read_sql_query(f"""
            SELECT
                COALESCE(district_norm, '(unknown)') as district_norm,
                COUNT(*) as n,
                AVG(transaction_price_per_m2) as mean_p,
                SUM(transaction_price) as volume
            FROM transactions
            WHERE transaction_date >= date('now', :days)
              AND transaction_price_per_m2 IS NOT NULL
              {pt_sql}
            GROUP BY COALESCE(district_norm, '(unknown)')
            ORDER BY n DESC
        """, conn, params=params)
        # Median per dzielnica via pandas
        raw = pd.read_sql_query(f"""
            SELECT COALESCE(district_norm, '(unknown)') as district_norm,
                   transaction_price_per_m2 as v
            FROM transactions
            WHERE transaction_date >= date('now', :days)
              AND transaction_price_per_m2 IS NOT NULL
              {pt_sql}
        """, conn, params=params)
        # display_name lookup
        names = pd.read_sql_query(
            "SELECT district_norm, display_name FROM geo_districts", conn
        )
    if not df.empty:
        med = raw.groupby("district_norm")["v"].median().rename("median_p")
        df = df.merge(med, on="district_norm", how="left")
        df = df.merge(names, on="district_norm", how="left")
        df["display_name"] = df["display_name"].fillna(df["district_norm"])
        df = df[["district_norm", "display_name", "n", "median_p", "mean_p", "volume"]]
    return df


def get_recent_transactions(
    property_type: str | None = None,
    limit: int = 100,
) -> pd.DataFrame:
    pt_sql, pt_p = _pt_clause(property_type)
    with get_conn() as conn:
        df = pd.read_sql_query(f"""
            SELECT
                transaction_date, property_type, market_type,
                district_norm, address, area_m2, rooms,
                transaction_price, transaction_price_per_m2, currency, source
            FROM transactions
            WHERE 1=1 {pt_sql}
            ORDER BY transaction_date DESC, imported_at DESC
            LIMIT :limit
        """, conn, params={**pt_p, "limit": limit})
    return df
