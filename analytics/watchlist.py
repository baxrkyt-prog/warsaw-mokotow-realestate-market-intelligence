"""
analytics/watchlist.py — operacje na watchliście i ekstrakcja cen w punkcie dodania.
"""

import pandas as pd

from database import get_conn


def get_watchlist_ids() -> set:
    with get_conn() as conn:
        rows = conn.execute("SELECT offer_id FROM watchlist").fetchall()
    return {r["offer_id"] for r in rows}


def set_watchlist(offer_id: str, watched: bool, note: str = ""):
    from datetime import datetime, timezone
    with get_conn() as conn:
        if watched:
            conn.execute("""
                INSERT OR REPLACE INTO watchlist (offer_id, added_ts, note)
                VALUES (?, ?, ?)
            """, (offer_id, datetime.now(timezone.utc).isoformat(), note))
        else:
            conn.execute("DELETE FROM watchlist WHERE offer_id = ?", (offer_id,))


def bulk_set_watchlist(offer_ids_add: list, offer_ids_remove: list):
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        for oid in offer_ids_add:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (offer_id, added_ts, note) VALUES (?, ?, '')",
                (oid, ts)
            )
        for oid in offer_ids_remove:
            conn.execute("DELETE FROM watchlist WHERE offer_id = ?", (oid,))


def get_watchlist_listings() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT
                l.offer_id, l.asset_class, l.transaction_type,
                l.title, l.url, l.subdistrict, l.building_name,
                l.area_m2, l.rooms, l.floor,
                l.price_total, l.price_per_m2, l.currency,
                l.advertiser_type, l.is_active,
                l.first_seen, l.last_seen,
                w.added_ts, w.note,
                (SELECT s.current_price FROM snapshots s
                 WHERE s.offer_id = l.offer_id
                 ORDER BY s.scrape_ts DESC LIMIT 1) AS current_price,
                (SELECT s.current_price_m2 FROM snapshots s
                 WHERE s.offer_id = l.offer_id
                 ORDER BY s.scrape_ts DESC LIMIT 1) AS current_price_m2,
                (SELECT s.current_price FROM snapshots s
                 WHERE s.offer_id = l.offer_id
                   AND s.scrape_ts <= w.added_ts
                 ORDER BY s.scrape_ts DESC LIMIT 1) AS price_at_add,
                (SELECT s.current_price_m2 FROM snapshots s
                 WHERE s.offer_id = l.offer_id
                   AND s.scrape_ts <= w.added_ts
                 ORDER BY s.scrape_ts DESC LIMIT 1) AS price_m2_at_add
            FROM watchlist w
            JOIN listings l ON l.offer_id = w.offer_id
            ORDER BY w.added_ts DESC
        """, conn)
    df["price_change"] = df["current_price"] - df["price_at_add"]
    df["price_change_pct"] = (
        df["price_change"] / df["price_at_add"].replace(0, float("nan")) * 100
    ).round(1)
    return df
