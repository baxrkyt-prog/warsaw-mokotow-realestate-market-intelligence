"""
analytics/runs.py — log uruchomień (back-compat: scrape_runs jest teraz VIEW na ingestion_runs).
"""

import pandas as pd

from database import get_conn


def get_scrape_log(limit: int = 50) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT run_ts, source, asset_class, offers_found,
                   new_listings, delisted, price_changes, status, error_msg
            FROM scrape_runs
            ORDER BY run_ts DESC
            LIMIT :limit
        """, conn, params={"limit": limit})
    return df


def get_last_scrape_ts() -> str:
    with get_conn() as conn:
        r = conn.execute("SELECT MAX(run_ts) as ts FROM scrape_runs").fetchone()
    return r["ts"][:16].replace("T", " ") + " UTC" if r and r["ts"] else "—"
