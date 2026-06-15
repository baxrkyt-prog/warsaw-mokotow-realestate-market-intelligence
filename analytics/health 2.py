"""
analytics/health.py — Market Health Score (Office + Residential).
Composite 0-100, 4 składowe x 25 pkt. Etykiety: STRONG/STABLE/CAUTIOUS/DISTRESSED.
"""

from database import get_conn


def _label(score: int) -> tuple[str, str]:
    if score >= 80:   return "STRONG",    "green"
    if score >= 60:   return "STABLE",    "gold"
    if score >= 40:   return "CAUTIOUS",  "amber"
    return                  "DISTRESSED", "red"


def compute_office_health_score() -> dict:
    """Score 0-100 z 4 składowych x 25 pkt."""
    with get_conn() as conn:
        r = conn.execute("""
            SELECT
                AVG(CASE WHEN s.scrape_date >= date('now','-14 days') THEN s.current_price_m2 END) as recent,
                AVG(CASE WHEN s.scrape_date BETWEEN date('now','-44 days') AND date('now','-15 days') THEN s.current_price_m2 END) as prev
            FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='office' AND s.current_price_m2 IS NOT NULL
        """).fetchone()
        if r and r["recent"] and r["prev"] and r["prev"] > 0:
            chg = (r["recent"] - r["prev"]) / r["prev"]
            c_rent = max(0.0, min(25.0, 12.5 + chg * 200))
        else:
            c_rent = 12.0

        a = conn.execute("""
            SELECT
                COUNT(CASE WHEN l.is_active=0 AND l.last_seen >= date('now','-30 days') THEN 1 END) as del30,
                COUNT(CASE WHEN l.first_seen >= date('now','-30 days') THEN 1 END) as new30
            FROM listings l WHERE l.asset_class='office'
        """).fetchone()
        if a and (a["del30"] + a["new30"]) > 0:
            c_abs = min(25.0, (a["del30"] / (a["del30"] + a["new30"])) * 50)
        else:
            c_abs = 10.0

        total = conn.execute("SELECT COUNT(*) as c FROM listings WHERE asset_class='office'").fetchone()
        active = conn.execute("SELECT COUNT(*) as c FROM listings WHERE asset_class='office' AND is_active=1").fetchone()
        if total and active and total["c"] > 0:
            c_vac = max(0.0, min(25.0, (1 - active["c"] / total["c"]) * 50))
        else:
            c_vac = 12.0

        s2 = conn.execute("""
            SELECT
                COUNT(CASE WHEN first_seen >= date('now','-7 days') THEN 1 END) as n7,
                COUNT(CASE WHEN first_seen BETWEEN date('now','-14 days') AND date('now','-8 days') THEN 1 END) as p7
            FROM listings WHERE asset_class='office'
        """).fetchone()
        if s2 and s2["p7"] and s2["p7"] > 0:
            surge = (s2["n7"] - s2["p7"]) / s2["p7"]
            c_supply = max(0.0, min(25.0, 25 - max(0.0, surge) * 60))
        else:
            c_supply = 18.0

    score = round(c_rent + c_abs + c_vac + c_supply)
    label, color = _label(score)
    return {
        "score": score, "label": label, "color": color,
        "components": {
            "Rent Trend":  round(c_rent, 1),
            "Absorption":  round(c_abs, 1),
            "Vacancy":     round(c_vac, 1),
            "Supply":      round(c_supply, 1),
        },
    }


def compute_project_health_score(project_id: str) -> dict:
    """Project Health Score 0-100 z 4 składowych × 25 pkt:
       A. Pricing      — stabilność/trend mediany ceny projektu (snapshoty)
       B. Velocity     — tempo sprzedaży jednostek (delisted 30d vs dostępne)
       C. Inventory    — sell-through (sprzedane / kiedykolwiek widziane)
       D. Tx Context   — dyscyplina cenowa: mediana projektu vs mediana transakcji dzielnicy
    """
    with get_conn() as conn:
        # A. Pricing trend — ostatni vs sprzed ~30 dni (snapshoty projektu)
        pr = conn.execute("""
            SELECT
                (SELECT median_price_m2 FROM project_snapshots
                 WHERE project_id=? AND median_price_m2 IS NOT NULL
                 ORDER BY scrape_date DESC LIMIT 1) as recent,
                (SELECT median_price_m2 FROM project_snapshots
                 WHERE project_id=? AND median_price_m2 IS NOT NULL
                   AND scrape_date <= date('now','-30 days')
                 ORDER BY scrape_date DESC LIMIT 1) as prev
        """, (project_id, project_id)).fetchone()
        if pr and pr["recent"] and pr["prev"] and pr["prev"] > 0:
            chg = (pr["recent"] - pr["prev"]) / pr["prev"]
            # rosnąca/stabilna cena = zdrowy projekt; spadek karany
            c_price = max(0.0, min(25.0, 12.5 + chg * 250))
        else:
            c_price = 12.5

        # B+C: jednostki projektu (invest_unit pod parent_project_id)
        units = conn.execute("""
            SELECT
                COUNT(*) as total_seen,
                COUNT(CASE WHEN is_active=1 THEN 1 END) as active,
                COUNT(CASE WHEN is_active=0 AND last_seen >= date('now','-30 days') THEN 1 END) as sold_30,
                COUNT(CASE WHEN is_active=0 THEN 1 END) as sold_total
            FROM listings
            WHERE parent_project_id=? AND transaction_type='invest_unit'
        """, (project_id,)).fetchone()
        total_seen = units["total_seen"] or 0
        active = units["active"] or 0
        sold_30 = units["sold_30"] or 0
        sold_total = units["sold_total"] or 0

        # Czy mamy wystarczającą głębię obserwacji, by w ogóle MIERZYĆ sprzedaż?
        # (project_snapshots = ile dni śledzimy projekt)
        snap_days = conn.execute(
            "SELECT COUNT(*) n FROM project_snapshots WHERE project_id=?", (project_id,)
        ).fetchone()["n"]
        observable = snap_days >= 14  # min 2 tygodnie historii by ocenić rotację

        # B. Velocity — sprzedane 30d względem dostępnych (im więcej rotacji, tym lepiej)
        if not observable and sold_total == 0:
            c_velocity = 12.5  # brak danych ≠ zła sprzedaż (neutralne)
        elif active + sold_30 > 0:
            c_velocity = min(25.0, (sold_30 / max(active + sold_30, 1)) * 60)
        else:
            c_velocity = 8.0

        # C. Inventory / sell-through
        if not observable and sold_total == 0:
            c_inventory = 12.5  # neutralne — za krótka historia
        elif total_seen > 0:
            c_inventory = min(25.0, (sold_total / total_seen) * 35)
        else:
            c_inventory = 8.0

        # D. Transaction context — mediana projektu vs mediana transakcji dzielnicy
        proj = conn.execute("""
            SELECT dp.subdistrict,
                   (SELECT median_price_m2 FROM project_snapshots
                    WHERE project_id=dp.project_id AND median_price_m2 IS NOT NULL
                    ORDER BY scrape_date DESC LIMIT 1) as proj_median
            FROM developer_projects dp WHERE dp.project_id=?
        """, (project_id,)).fetchone()
        c_tx = 12.5
        tx_note = "brak danych transakcyjnych dzielnicy"
        if proj and proj["proj_median"] and proj["subdistrict"]:
            from database import normalize_district
            dn = normalize_district(proj["subdistrict"])
            if dn:
                txr = conn.execute("""
                    SELECT AVG(transaction_price_per_m2) as tx_med, COUNT(*) n
                    FROM transactions
                    WHERE district_norm=? AND property_type='residential'
                      AND transaction_date >= date('now','-180 days')
                      AND transaction_price_per_m2 IS NOT NULL
                """, (dn,)).fetchone()
                if txr and txr["tx_med"] and txr["n"] >= 3:
                    gap = (proj["proj_median"] - txr["tx_med"]) / txr["tx_med"]
                    # im bliżej cen transakcyjnych, tym zdrowsza wycena (mała |gap| = wysoki score)
                    c_tx = max(0.0, min(25.0, 25 - abs(gap) * 60))
                    tx_note = f"projekt {gap*100:+.0f}% vs transakcje dzielnicy"

    score = round(c_price + c_velocity + c_inventory + c_tx)
    if score >= 75:   label, color = "HEALTHY",   "green"
    elif score >= 55: label, color = "STABLE",    "gold"
    elif score >= 35: label, color = "WATCH",     "amber"
    else:             label, color = "AT RISK",   "red"

    return {
        "score": score, "label": label, "color": color,
        "components": {
            "Pricing":     round(c_price, 1),
            "Velocity":    round(c_velocity, 1),
            "Inventory":   round(c_inventory, 1),
            "Tx Context":  round(c_tx, 1),
        },
        "notes": {
            "sold_30d": sold_30, "active_units": active,
            "sell_through_pct": round(sold_total / total_seen * 100, 1) if total_seen else None,
            "tx_context": tx_note,
        },
    }


def compute_residential_health_score() -> dict:
    """Score 0-100 z 4 składowych x 25 pkt."""
    with get_conn() as conn:
        r = conn.execute("""
            SELECT
                AVG(CASE WHEN s.scrape_date >= date('now','-14 days') THEN s.current_price_m2 END) as recent,
                AVG(CASE WHEN s.scrape_date BETWEEN date('now','-44 days') AND date('now','-15 days') THEN s.current_price_m2 END) as prev
            FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='residential' AND l.transaction_type='sale' AND s.current_price_m2 IS NOT NULL
        """).fetchone()
        if r and r["recent"] and r["prev"] and r["prev"] > 0:
            chg = (r["recent"] - r["prev"]) / r["prev"]
            c_price = max(0.0, min(25.0, 12.5 + chg * 200))
        else:
            c_price = 12.0

        al = conn.execute("""
            SELECT COUNT(*) as c FROM listings WHERE asset_class='residential' AND transaction_type='sale' AND is_active=1
        """).fetchone()
        total_r = conn.execute("SELECT COUNT(*) as c FROM listings WHERE asset_class='residential' AND transaction_type='sale'").fetchone()
        if al and total_r and total_r["c"] > 0:
            active_ratio = al["c"] / total_r["c"]
            c_listings = max(0.0, min(25.0, active_ratio * 35))
        else:
            c_listings = 12.0

        drops = conn.execute("""
            SELECT COUNT(*) as c FROM listings
            WHERE asset_class='residential' AND transaction_type='sale'
              AND is_active=1
              AND price_total < (
                  SELECT MIN(s2.current_price) FROM snapshots s2
                  WHERE s2.offer_id=listings.offer_id AND s2.active_status=1
              )
        """).fetchone()
        drop_count = drops["c"] if drops and drops["c"] else 0
        active_count = al["c"] if al else 1
        drop_ratio = drop_count / max(active_count, 1)
        c_reductions = max(0.0, min(25.0, (1 - drop_ratio * 5) * 25))

        s2 = conn.execute("""
            SELECT
                COUNT(CASE WHEN first_seen >= date('now','-7 days') THEN 1 END) as n7,
                COUNT(CASE WHEN first_seen BETWEEN date('now','-14 days') AND date('now','-8 days') THEN 1 END) as p7
            FROM listings WHERE asset_class='residential' AND transaction_type='sale'
        """).fetchone()
        if s2 and s2["p7"] and s2["p7"] > 0:
            surge = (s2["n7"] - s2["p7"]) / s2["p7"]
            c_supply = max(0.0, min(25.0, 25 - max(0.0, surge) * 40))
        else:
            c_supply = 18.0

    score = round(c_price + c_listings + c_reductions + c_supply)
    label, color = _label(score)
    return {
        "score": score, "label": label, "color": color,
        "components": {
            "Price Trend":      round(c_price, 1),
            "Active Listings":  round(c_listings, 1),
            "Price Reductions": round(c_reductions, 1),
            "New Supply":       round(c_supply, 1),
        },
    }
