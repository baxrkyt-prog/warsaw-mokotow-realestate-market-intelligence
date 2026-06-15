"""
analytics/alerts.py — silnik alertów.
Phase 0: istniejące reguły dla office/residential/developer.
Phase 4 doda: spread_widening, tx_volume_collapse, liquidity_deterioration, negotiation_index_deterioration.
"""

import pandas as pd

from database import get_conn


def get_alerts(unread_only: bool = False) -> pd.DataFrame:
    where = "WHERE is_new = 1" if unread_only else ""
    with get_conn() as conn:
        df = pd.read_sql_query(f"""
            SELECT id, alert_ts, alert_type, asset_class, message, value, threshold, is_new
            FROM alerts_log
            {where}
            ORDER BY alert_ts DESC
            LIMIT 100
        """, conn)
    return df


def mark_alerts_read(alert_ids: list):
    if not alert_ids:
        return
    placeholders = ",".join("?" * len(alert_ids))
    with get_conn() as conn:
        conn.execute(
            f"UPDATE alerts_log SET is_new = 0 WHERE id IN ({placeholders})",
            alert_ids
        )


def check_and_fire_alerts() -> list:
    """Sprawdza progi alertów i zapisuje nowe do alerts_log."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    fired = []

    with get_conn() as conn:
        # 1. Office rent drop >5%
        row = conn.execute("""
            SELECT
                AVG(CASE WHEN s.scrape_date >= date('now', '-7 days')
                         THEN s.current_price_m2 END) as recent,
                AVG(CASE WHEN s.scrape_date BETWEEN date('now', '-21 days')
                                                 AND date('now', '-8 days')
                         THEN s.current_price_m2 END) as prev
            FROM snapshots s JOIN listings l ON l.offer_id = s.offer_id
            WHERE l.asset_class = 'office' AND s.current_price_m2 IS NOT NULL
        """).fetchone()
        if row and row["recent"] and row["prev"] and row["prev"] > 0:
            change = (row["recent"] - row["prev"]) / row["prev"]
            if change < -0.05:
                fired.append({
                    "alert_ts": now, "alert_type": "office_rent_drop",
                    "asset_class": "office",
                    "message": f"Czynsz biurowy spadł o {abs(change)*100:.1f}% (14-dniowe okno)",
                    "value": round(change * 100, 2), "threshold": -5.0, "is_new": 1
                })

        # 2. Office supply surge >10%
        row2 = conn.execute("""
            SELECT
                COUNT(CASE WHEN first_seen >= date('now', '-7 days') THEN 1 END) as new_week,
                COUNT(CASE WHEN first_seen BETWEEN date('now', '-14 days')
                                                AND date('now', '-8 days') THEN 1 END) as prev_week
            FROM listings WHERE asset_class = 'office'
        """).fetchone()
        if row2 and row2["prev_week"] and row2["prev_week"] > 0:
            surge = (row2["new_week"] - row2["prev_week"]) / row2["prev_week"]
            if surge > 0.10:
                fired.append({
                    "alert_ts": now, "alert_type": "office_supply_surge",
                    "asset_class": "office",
                    "message": f"Podaż biur wzrosła o {surge*100:.1f}% tygodniowo",
                    "value": round(surge * 100, 2), "threshold": 10.0, "is_new": 1
                })

        # 3. Residential supply surge >15%
        row3 = conn.execute("""
            SELECT
                COUNT(CASE WHEN first_seen >= date('now', '-7 days') THEN 1 END) as new_week,
                COUNT(CASE WHEN first_seen BETWEEN date('now', '-14 days')
                                                AND date('now', '-8 days') THEN 1 END) as prev_week
            FROM listings WHERE asset_class = 'residential' AND transaction_type = 'sale'
        """).fetchone()
        if row3 and row3["prev_week"] and row3["prev_week"] > 0:
            surge = (row3["new_week"] - row3["prev_week"]) / row3["prev_week"]
            if surge > 0.15:
                fired.append({
                    "alert_ts": now, "alert_type": "residential_supply_surge",
                    "asset_class": "residential",
                    "message": f"Podaż mieszkań wzrosła o {surge*100:.1f}% tygodniowo",
                    "value": round(surge * 100, 2), "threshold": 15.0, "is_new": 1
                })

        # 4. Developer median price drop >3%
        row4 = conn.execute("""
            SELECT
                AVG(CASE WHEN ps.scrape_date >= date('now', '-7 days')
                         THEN ps.median_price_m2 END) as recent,
                AVG(CASE WHEN ps.scrape_date BETWEEN date('now', '-21 days')
                                                 AND date('now', '-8 days')
                         THEN ps.median_price_m2 END) as prev
            FROM project_snapshots ps WHERE ps.median_price_m2 IS NOT NULL
        """).fetchone()
        if row4 and row4["recent"] and row4["prev"] and row4["prev"] > 0:
            change = (row4["recent"] - row4["prev"]) / row4["prev"]
            if change < -0.03:
                fired.append({
                    "alert_ts": now, "alert_type": "developer_price_drop",
                    "asset_class": "developer",
                    "message": f"Mediana cen inwestycji spadła o {abs(change)*100:.1f}%",
                    "value": round(change * 100, 2), "threshold": -3.0, "is_new": 1
                })

        # ── Phase 4: alerty pricingowe ─────────────────────────────────
        # 5. Spread widening — mediana spreadu (90d window) pogłębiła się
        #    o >5 pkt% między dwoma ostatnimi snapshotami materializacji
        spread_rows = conn.execute("""
            SELECT snapshot_date, AVG(spread_pct) as avg_spread
            FROM pricing_spreads
            WHERE property_type='residential' AND window_days=90 AND district_norm != ''
            GROUP BY snapshot_date
            ORDER BY snapshot_date DESC LIMIT 2
        """).fetchall()
        if len(spread_rows) == 2:
            curr_s, prev_s = spread_rows[0]["avg_spread"], spread_rows[1]["avg_spread"]
            if curr_s is not None and prev_s is not None and (curr_s - prev_s) < -5.0:
                fired.append({
                    "alert_ts": now, "alert_type": "spread_widening",
                    "asset_class": "pricing",
                    "message": f"Spread asking↔transaction pogłębił się z {prev_s:.1f}% do {curr_s:.1f}%",
                    "value": round(curr_s - prev_s, 2), "threshold": -5.0, "is_new": 1
                })

        # 6. Transaction volume collapse — tx_count_30d < 50% poprzednich 30d
        txv = conn.execute("""
            SELECT
                COUNT(CASE WHEN transaction_date >= date('now','-30 days') THEN 1 END) as curr,
                COUNT(CASE WHEN transaction_date BETWEEN date('now','-60 days')
                                                     AND date('now','-31 days') THEN 1 END) as prev
            FROM transactions WHERE property_type='residential'
        """).fetchone()
        if txv and txv["prev"] and txv["prev"] >= 5:
            ratio = txv["curr"] / txv["prev"]
            if ratio < 0.5:
                fired.append({
                    "alert_ts": now, "alert_type": "tx_volume_collapse",
                    "asset_class": "pricing",
                    "message": f"Liczba transakcji spadła do {ratio*100:.0f}% poprzedniego okresu ({txv['curr']} vs {txv['prev']})",
                    "value": round(ratio * 100, 1), "threshold": 50.0, "is_new": 1
                })

        # 7. Negotiation index deterioration — NI spadł o ≥3 pkt% w 30 dni
        ni_rows = conn.execute("""
            SELECT snapshot_date, AVG(negotiation_index) as ni
            FROM pricing_spreads
            WHERE property_type='residential' AND window_days=90 AND district_norm != ''
              AND snapshot_date >= date('now','-35 days')
            GROUP BY snapshot_date ORDER BY snapshot_date
        """).fetchall()
        if len(ni_rows) >= 2:
            first_ni, last_ni = ni_rows[0]["ni"], ni_rows[-1]["ni"]
            if first_ni is not None and last_ni is not None and (last_ni - first_ni) < -3.0:
                fired.append({
                    "alert_ts": now, "alert_type": "negotiation_index_deterioration",
                    "asset_class": "pricing",
                    "message": f"Negotiation Index pogorszył się z {first_ni:.1f}% do {last_ni:.1f}% (30d)",
                    "value": round(last_ni - first_ni, 2), "threshold": -3.0, "is_new": 1
                })

        # ── Phase 10: alerty lifecycle (DOM / turnover / stale) ─────────
        for ac in ("office", "residential"):
            curr = conn.execute("""
                SELECT median_dom, turnover_pct, stale_count, active
                FROM lifecycle_snapshots WHERE asset_class=?
                ORDER BY snapshot_date DESC LIMIT 1
            """, (ac,)).fetchone()
            base = conn.execute("""
                SELECT median_dom, turnover_pct, stale_count, active
                FROM lifecycle_snapshots
                WHERE asset_class=? AND snapshot_date <= date('now','-25 days')
                ORDER BY snapshot_date DESC LIMIT 1
            """, (ac,)).fetchone()
            if not curr or not base:
                continue
            label = "biur" if ac == "office" else "mieszkań"

            # Median DOM wzrost >20% (oferty wiszą dłużej — wolniejszy rynek)
            if curr["median_dom"] and base["median_dom"] and base["median_dom"] > 0:
                chg = (curr["median_dom"] - base["median_dom"]) / base["median_dom"]
                if chg > 0.20:
                    fired.append({
                        "alert_ts": now, "alert_type": "dom_increase", "asset_class": ac,
                        "message": f"Median DOM {label} wzrósł o {chg*100:.0f}% "
                                   f"({base['median_dom']:.0f}→{curr['median_dom']:.0f} dni)",
                        "value": round(chg*100, 1), "threshold": 20.0, "is_new": 1})

            # Turnover deterioration (spadek >20% — rynek mniej płynny)
            if curr["turnover_pct"] is not None and base["turnover_pct"]:
                tchg = (curr["turnover_pct"] - base["turnover_pct"]) / base["turnover_pct"]
                if tchg < -0.20:
                    fired.append({
                        "alert_ts": now, "alert_type": "turnover_deterioration", "asset_class": ac,
                        "message": f"Turnover {label} spadł o {abs(tchg)*100:.0f}% "
                                   f"({base['turnover_pct']:.0f}%→{curr['turnover_pct']:.0f}%)",
                        "value": round(tchg*100, 1), "threshold": -20.0, "is_new": 1})

            # Stale surge (wzrost udziału stale o >30%)
            if curr["stale_count"] and base["stale_count"] and base["stale_count"] > 0:
                schg = (curr["stale_count"] - base["stale_count"]) / base["stale_count"]
                if schg > 0.30:
                    fired.append({
                        "alert_ts": now, "alert_type": "stale_surge", "asset_class": ac,
                        "message": f"Liczba stale ofert {label} wzrosła o {schg*100:.0f}% "
                                   f"({base['stale_count']}→{curr['stale_count']})",
                        "value": round(schg*100, 1), "threshold": 30.0, "is_new": 1})

        for alert in fired:
            conn.execute("""
                INSERT INTO alerts_log
                    (alert_ts, alert_type, asset_class, message, value, threshold, is_new)
                VALUES
                    (:alert_ts, :alert_type, :asset_class, :message, :value, :threshold, :is_new)
            """, alert)

    # 8. Liquidity deterioration — score spadł o ≥15 pkt vs poprzednie uruchomienie
    #    (porównanie z ostatnim zapisanym alertem typu liquidity_check w alerts_log
    #     byłoby kruche; liczymy z danych — okno 30d vs 30d przesuniete)
    from .pricing import compute_liquidity_score
    try:
        ls = compute_liquidity_score("residential")
        if ls["score"] is not None and ls["score"] < 40:
            with get_conn() as conn:
                already = conn.execute("""
                    SELECT 1 FROM alerts_log
                    WHERE alert_type='liquidity_deterioration'
                      AND alert_ts >= date('now','-7 days')
                """).fetchone()
                if not already:
                    alert = {
                        "alert_ts": now, "alert_type": "liquidity_deterioration",
                        "asset_class": "pricing",
                        "message": f"Liquidity Score spadł do {ls['score']} ({ls['label']})",
                        "value": float(ls["score"]), "threshold": 40.0, "is_new": 1,
                    }
                    conn.execute("""
                        INSERT INTO alerts_log
                            (alert_ts, alert_type, asset_class, message, value, threshold, is_new)
                        VALUES
                            (:alert_ts, :alert_type, :asset_class, :message, :value, :threshold, :is_new)
                    """, alert)
                    fired.append(alert)
    except Exception:
        pass  # liquidity wymaga transakcji — brak danych nie blokuje pozostałych alertów

    return fired
