"""
analytics.py — funkcje analityczne Ocean Plaza Market Intelligence. v3
"""

from typing import Optional
import pandas as pd
import numpy as np
from scipy import stats as scipy_stats

from database import get_conn, ZONE_MAP, COMPETITIVE_SET

# ──────────────────────────────────────────────
# BIURA
# ──────────────────────────────────────────────

def get_office_summary() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT
                l.offer_id, l.title, l.url,
                l.area_m2, l.building_name, l.building_class,
                l.price_total, l.price_per_m2, l.advertiser_type,
                l.subdistrict, l.first_seen, l.last_seen, l.is_active
            FROM listings l
            WHERE l.asset_class = 'office'
              AND l.is_active = 1
        """, conn)
    return df


def get_office_trend(days: int = 90) -> pd.DataFrame:
    """Trend średniego czynszu biurowego zł/m²/msc po datach."""
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT
                s.scrape_date,
                AVG(s.current_price_m2) as avg_price_m2,
                COUNT(*) as count
            FROM snapshots s
            JOIN listings l ON l.offer_id = s.offer_id
            WHERE l.asset_class = 'office'
              AND s.active_status = 1
              AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date >= date('now', :days)
            GROUP BY s.scrape_date
            ORDER BY s.scrape_date
        """, conn, params={"days": f"-{days} days"})
    return df


def get_office_vacancy_proxy() -> pd.DataFrame:
    """Szacunkowa podaż biur wg budynku (liczba aktywnych ofert)."""
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT
                COALESCE(building_name, 'Inne') as building,
                building_class,
                COUNT(*) as active_offers,
                AVG(area_m2) as avg_area,
                AVG(price_per_m2) as avg_price_m2,
                MIN(price_per_m2) as min_price_m2,
                MAX(price_per_m2) as max_price_m2
            FROM listings
            WHERE asset_class = 'office' AND is_active = 1
            GROUP BY COALESCE(building_name, 'Inne'), building_class
            ORDER BY active_offers DESC
        """, conn)
    return df


def get_competitive_set() -> pd.DataFrame:
    """Oferty z competitive set (Ocean Plaza, Curtis Plaza, New City, Marynarska)."""
    conditions = []
    for building, keywords in COMPETITIVE_SET.items():
        for kw in keywords:
            kw_escaped = kw.replace("'", "''")
            conditions.append(
                f"(LOWER(COALESCE(title,'') || ' ' || COALESCE(building_name,'')) LIKE '%{kw_escaped}%')"
            )
    where = " OR ".join(conditions)

    with get_conn() as conn:
        df = pd.read_sql_query(f"""
            SELECT
                offer_id, title, building_name, area_m2,
                price_total, price_per_m2, building_class,
                first_seen, is_active
            FROM listings
            WHERE asset_class = 'office'
              AND ({where})
            ORDER BY building_name, price_per_m2
        """, conn)

    def label_building(row):
        text = ((row.get("title") or "") + " " + (row.get("building_name") or "")).lower()
        for bname, keywords in COMPETITIVE_SET.items():
            for kw in keywords:
                if kw in text:
                    return bname
        return "Inne"

    if not df.empty:
        df["competitive_building"] = df.apply(label_building, axis=1)
    return df


def get_office_zone_summary() -> pd.DataFrame:
    """Podsumowanie podaży biur wg strefy (500m/1km/2km od Ocean Plaza)."""
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT subdistrict, COUNT(*) as count,
                   AVG(price_per_m2) as avg_price_m2,
                   AVG(area_m2) as avg_area
            FROM listings
            WHERE asset_class = 'office' AND is_active = 1
            GROUP BY subdistrict
        """, conn)

    def assign_zone(sub):
        if not sub:
            return "poza strefą"
        sub_l = sub.lower()
        for zone, subdistricts in ZONE_MAP.items():
            if sub_l in subdistricts:
                return zone
        return "poza strefą"

    df["zone"] = df["subdistrict"].apply(assign_zone)
    return df


# ──────────────────────────────────────────────
# RESIDENTIAL (SPRZEDAŻ)
# ──────────────────────────────────────────────

def get_residential_summary() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT
                l.offer_id, l.title, l.subdistrict,
                l.area_m2, l.rooms, l.floor,
                l.price_total, l.price_per_m2,
                l.advertiser_type, l.first_seen, l.is_active
            FROM listings l
            WHERE l.asset_class = 'residential'
              AND l.transaction_type = 'sale'
              AND l.is_active = 1
        """, conn)
    return df


def get_residential_trend(days: int = 90) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT
                s.scrape_date,
                AVG(s.current_price_m2) as avg_price_m2,
                COUNT(*) as count
            FROM snapshots s
            JOIN listings l ON l.offer_id = s.offer_id
            WHERE l.asset_class = 'residential'
              AND l.transaction_type = 'sale'
              AND s.active_status = 1
              AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date >= date('now', :days)
            GROUP BY s.scrape_date
            ORDER BY s.scrape_date
        """, conn, params={"days": f"-{days} days"})
    return df


def get_residential_zone_summary() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT subdistrict, COUNT(*) as count,
                   AVG(price_per_m2) as avg_price_m2,
                   AVG(area_m2) as avg_area
            FROM listings
            WHERE asset_class = 'residential'
              AND transaction_type = 'sale'
              AND is_active = 1
            GROUP BY subdistrict
        """, conn)

    def assign_zone(sub):
        if not sub:
            return "poza strefą"
        sub_l = sub.lower()
        for zone, subdistricts in ZONE_MAP.items():
            if sub_l in subdistricts:
                return zone
        return "poza strefą"

    df["zone"] = df["subdistrict"].apply(assign_zone)
    return df


# ──────────────────────────────────────────────
# DEVELOPER PROJECTS
# ──────────────────────────────────────────────

def get_developer_projects() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT
                dp.project_id, dp.name, dp.developer, dp.subdistrict,
                dp.first_seen, dp.last_seen, dp.is_active,
                ps.units_available, ps.median_price_m2, ps.avg_price_m2,
                ps.min_price, ps.max_price, ps.scrape_date as last_snapshot_date
            FROM developer_projects dp
            LEFT JOIN project_snapshots ps ON ps.project_id = dp.project_id
                AND ps.scrape_date = (
                    SELECT MAX(scrape_date) FROM project_snapshots
                    WHERE project_id = dp.project_id
                )
            ORDER BY dp.is_active DESC, ps.units_available DESC
        """, conn)
    return df


def get_project_snapshots(project_id: str, days: int = 90) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT scrape_date, units_available, median_price_m2,
                   avg_price_m2, min_price, max_price
            FROM project_snapshots
            WHERE project_id = :pid
              AND scrape_date >= date('now', :days)
            ORDER BY scrape_date
        """, conn, params={"pid": project_id, "days": f"-{days} days"})
    return df


def get_sales_velocity(project_id: Optional[str] = None, window_days: int = 30) -> pd.DataFrame:
    """
    Sales Velocity = liczba jednostek sprzedanych (delisted) w oknie czasowym.
    """
    pid_filter = "AND l.parent_project_id = :pid" if project_id else ""
    params: dict = {"days": f"-{window_days} days", "window_days": window_days}
    if project_id:
        params["pid"] = project_id

    with get_conn() as conn:
        df = pd.read_sql_query(f"""
            SELECT
                l.parent_project_id as project_id,
                dp.name as project_name,
                COUNT(*) as units_sold,
                ROUND(COUNT(*) * 1.0 / :window_days, 2) as units_per_day
            FROM snapshots s
            JOIN listings l ON l.offer_id = s.offer_id
            LEFT JOIN developer_projects dp ON dp.project_id = l.parent_project_id
            WHERE l.transaction_type = 'invest_unit'
              AND s.active_status = 0
              AND s.scrape_date >= date('now', :days)
              {pid_filter}
            GROUP BY l.parent_project_id, dp.name
            ORDER BY units_sold DESC
        """, conn, params=params)
    return df


def get_invest_units_summary() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT
                l.parent_project_id, dp.name as project_name,
                COUNT(*) as active_units,
                AVG(l.price_per_m2) as avg_price_m2,
                AVG(l.area_m2) as avg_area
            FROM listings l
            LEFT JOIN developer_projects dp ON dp.project_id = l.parent_project_id
            WHERE l.transaction_type = 'invest_unit'
              AND l.is_active = 1
            GROUP BY l.parent_project_id, dp.name
            ORDER BY active_units DESC
        """, conn)
    return df


# ──────────────────────────────────────────────
# ALERTY
# ──────────────────────────────────────────────

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

        for alert in fired:
            conn.execute("""
                INSERT INTO alerts_log
                    (alert_ts, alert_type, asset_class, message, value, threshold, is_new)
                VALUES
                    (:alert_ts, :alert_type, :asset_class, :message, :value, :threshold, :is_new)
            """, alert)

    return fired


# ──────────────────────────────────────────────
# FORECASTING (regresja liniowa)
# ──────────────────────────────────────────────

def forecast_trend(df: pd.DataFrame, date_col: str, value_col: str, horizon_days: int = 30) -> pd.DataFrame:
    """Liniowy trend + przedział ufności 95%."""
    if df.empty or value_col not in df.columns:
        return pd.DataFrame()
    df = df.dropna(subset=[date_col, value_col]).copy()
    if len(df) < 3:
        return pd.DataFrame()

    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    x = (df[date_col] - df[date_col].min()).dt.days.values
    y = df[value_col].values

    slope, intercept, _, _, _ = scipy_stats.linregress(x, y)
    last_day = x[-1]
    future_x = np.arange(last_day + 1, last_day + horizon_days + 1)
    future_dates = df[date_col].max() + pd.to_timedelta(future_x - last_day, unit="D")

    forecast = intercept + slope * future_x
    residuals = y - (intercept + slope * x)
    rmse = float(np.sqrt(np.mean(residuals ** 2)))

    return pd.DataFrame({
        "date": future_dates,
        "forecast": forecast,
        "lower": forecast - 1.96 * rmse,
        "upper": forecast + 1.96 * rmse,
    })


def get_office_forecast(days: int = 90, horizon: int = 30) -> tuple:
    hist = get_office_trend(days)
    fcast = forecast_trend(hist, "scrape_date", "avg_price_m2", horizon) if not hist.empty else pd.DataFrame()
    return hist, fcast


def get_residential_forecast(days: int = 90, horizon: int = 30) -> tuple:
    hist = get_residential_trend(days)
    fcast = forecast_trend(hist, "scrape_date", "avg_price_m2", horizon) if not hist.empty else pd.DataFrame()
    return hist, fcast


# ──────────────────────────────────────────────
# OCEAN PLAZA KPIs
# ──────────────────────────────────────────────

def get_ocean_plaza_kpis() -> dict:
    comp = get_competitive_set()
    all_office = get_office_summary()

    op = comp[comp["competitive_building"] == "Ocean Plaza"] if not comp.empty else pd.DataFrame()

    market_avg = all_office["price_per_m2"].mean() if not all_office.empty else None
    op_avg = op["price_per_m2"].mean() if not op.empty else None
    premium = ((op_avg - market_avg) / market_avg * 100) if (op_avg and market_avg and market_avg > 0) else None

    return {
        "op_active_offers": len(op),
        "op_avg_price_m2":  round(op_avg, 2) if op_avg else None,
        "market_avg_price": round(market_avg, 2) if market_avg else None,
        "op_premium_pct":   round(premium, 1) if premium is not None else None,
        "op_avg_area":      round(float(op["area_m2"].mean()), 1) if not op.empty and "area_m2" in op.columns and not op["area_m2"].isna().all() else None,
    }


# ──────────────────────────────────────────────
# SCRAPE LOG
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# HEALTH SCORES
# ──────────────────────────────────────────────

def _mom_delta(curr, prev):
    if curr is not None and prev is not None and prev > 0:
        return round((curr - prev) / prev * 100, 1)
    return None


def compute_office_health_score() -> dict:
    """Score 0–100 z 4 składowych × 25 pkt."""
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
    if score >= 80:   label, color = "STRONG",    "green"
    elif score >= 60: label, color = "STABLE",    "gold"
    elif score >= 40: label, color = "CAUTIOUS",  "amber"
    else:             label, color = "DISTRESSED", "red"

    return {
        "score": score, "label": label, "color": color,
        "components": {
            "Rent Trend":  round(c_rent, 1),
            "Absorption":  round(c_abs, 1),
            "Vacancy":     round(c_vac, 1),
            "Supply":      round(c_supply, 1),
        },
    }


def compute_residential_health_score() -> dict:
    """Score 0–100 z 4 składowych × 25 pkt."""
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
    if score >= 80:   label, color = "STRONG",    "green"
    elif score >= 60: label, color = "STABLE",    "gold"
    elif score >= 40: label, color = "CAUTIOUS",  "amber"
    else:             label, color = "DISTRESSED", "red"

    return {
        "score": score, "label": label, "color": color,
        "components": {
            "Price Trend":    round(c_price, 1),
            "Active Listings": round(c_listings, 1),
            "Price Reductions": round(c_reductions, 1),
            "New Supply":      round(c_supply, 1),
        },
    }


# ──────────────────────────────────────────────
# KPI S Z DELTAMI M/M
# ──────────────────────────────────────────────

def get_office_kpis_with_deltas() -> dict:
    with get_conn() as conn:
        # Ceny bieżące z ostatnich 7 dni
        prices_curr = conn.execute("""
            SELECT
                AVG(s.current_price_m2)  as avg_p,
                MIN(s.current_price_m2)  as min_p,
                MAX(s.current_price_m2)  as max_p
            FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='office' AND s.active_status=1
              AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date >= date('now','-7 days')
        """).fetchone()

        # Ceny sprzed ~30 dni (delta m/m)
        prices_prev = conn.execute("""
            SELECT AVG(s.current_price_m2) as avg_p
            FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='office' AND s.active_status=1
              AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date BETWEEN date('now','-37 days') AND date('now','-23 days')
        """).fetchone()

        # Mediana przez percentyl (SQLite nie ma MEDIAN — liczymy przez NTILE)
        median_row = conn.execute("""
            SELECT price_per_m2 FROM listings
            WHERE asset_class='office' AND is_active=1 AND price_per_m2 IS NOT NULL
            ORDER BY price_per_m2
            LIMIT 1 OFFSET (
                SELECT COUNT(*)/2 FROM listings
                WHERE asset_class='office' AND is_active=1 AND price_per_m2 IS NOT NULL
            )
        """).fetchone()

        # Metraże
        areas = conn.execute("""
            SELECT
                COUNT(*)        as n,
                SUM(area_m2)    as total,
                AVG(area_m2)    as avg_a,
                MIN(area_m2)    as min_a,
                MAX(area_m2)    as max_a
            FROM listings
            WHERE asset_class='office' AND is_active=1 AND area_m2 IS NOT NULL
        """).fetchone()

        median_area = conn.execute("""
            SELECT area_m2 FROM listings
            WHERE asset_class='office' AND is_active=1 AND area_m2 IS NOT NULL
            ORDER BY area_m2
            LIMIT 1 OFFSET (
                SELECT COUNT(*)/2 FROM listings
                WHERE asset_class='office' AND is_active=1 AND area_m2 IS NOT NULL
            )
        """).fetchone()

        ac = conn.execute(
            "SELECT COUNT(*) as c FROM listings WHERE asset_class='office' AND is_active=1"
        ).fetchone()
        ac_p = conn.execute("""
            SELECT COUNT(DISTINCT s.offer_id) as c FROM snapshots s
            JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='office' AND s.active_status=1
              AND s.scrape_date BETWEEN date('now','-37 days') AND date('now','-23 days')
        """).fetchone()

        new30 = conn.execute(
            "SELECT COUNT(*) as c FROM listings WHERE asset_class='office' AND first_seen >= date('now','-30 days')"
        ).fetchone()
        new60 = conn.execute(
            "SELECT COUNT(*) as c FROM listings WHERE asset_class='office' AND first_seen BETWEEN date('now','-60 days') AND date('now','-31 days')"
        ).fetchone()
        abs30 = conn.execute(
            "SELECT COUNT(*) as c FROM listings WHERE asset_class='office' AND is_active=0 AND last_seen >= date('now','-30 days')"
        ).fetchone()

        # Podział wystawiających
        adv = conn.execute("""
            SELECT advertiser_type, COUNT(*) as c
            FROM listings WHERE asset_class='office' AND is_active=1
            GROUP BY advertiser_type
        """).fetchall()

    avg_p   = round(prices_curr["avg_p"], 0) if prices_curr and prices_curr["avg_p"] else None
    prev_p  = prices_prev["avg_p"] if prices_prev else None
    med_p   = round(median_row["price_per_m2"], 0) if median_row and median_row["price_per_m2"] else None
    min_p   = round(prices_curr["min_p"], 0) if prices_curr and prices_curr["min_p"] else None
    max_p   = round(prices_curr["max_p"], 0) if prices_curr and prices_curr["max_p"] else None

    active   = ac["c"] if ac else 0
    active_p = ac_p["c"] if ac_p else None

    avg_area  = round(areas["avg_a"], 0) if areas and areas["avg_a"] else None
    med_area  = round(median_area["area_m2"], 0) if median_area and median_area["area_m2"] else None
    total_m2  = round((areas["total"] or 0) / 1000, 1) if areas else None
    min_area  = round(areas["min_a"], 0) if areas and areas["min_a"] else None
    max_area  = round(areas["max_a"], 0) if areas and areas["max_a"] else None

    new      = new30["c"] if new30 else 0
    new_p_v  = new60["c"] if new60 else None
    absorbed = abs30["c"] if abs30 else 0

    adv_dict = {r["advertiser_type"]: r["c"] for r in adv} if adv else {}
    pct_agency = round(adv_dict.get("agency", 0) / max(active, 1) * 100)
    pct_dev    = round(adv_dict.get("developer", 0) / max(active, 1) * 100)
    pct_priv   = round(adv_dict.get("private", 0) / max(active, 1) * 100)

    return {
        # Stawki
        "avg_rent":        {"value": avg_p,    "delta": _mom_delta(avg_p, prev_p),    "unit": "PLN/m²/mc śr.",    "inverse": False, "group": "Stawki"},
        "median_rent":     {"value": med_p,    "delta": None,                          "unit": "PLN/m²/mc med.",   "inverse": False, "group": "Stawki"},
        "min_rent":        {"value": min_p,    "delta": None,                          "unit": "PLN/m²/mc min",    "inverse": False, "group": "Stawki"},
        "max_rent":        {"value": max_p,    "delta": None,                          "unit": "PLN/m²/mc max",    "inverse": False, "group": "Stawki"},
        # Podaż
        "active_count":    {"value": active,   "delta": _mom_delta(active, active_p),  "unit": "ofert aktywnych",  "inverse": True,  "group": "Podaż"},
        "total_space":     {"value": total_m2, "delta": None,                          "unit": "tys. m² łącznie",  "inverse": True,  "group": "Podaż"},
        "new_30d":         {"value": new,      "delta": _mom_delta(new, new_p_v),      "unit": "nowych (30d)",     "inverse": True,  "group": "Podaż"},
        "absorbed_30d":    {"value": absorbed, "delta": None,                          "unit": "zdjętych (30d)",   "inverse": False, "group": "Podaż"},
        # Metraże
        "avg_area":        {"value": avg_area, "delta": None,                          "unit": "m² śr. pow.",      "inverse": False, "group": "Metraże"},
        "median_area":     {"value": med_area, "delta": None,                          "unit": "m² mediana",       "inverse": False, "group": "Metraże"},
        "min_area":        {"value": min_area, "delta": None,                          "unit": "m² min",           "inverse": False, "group": "Metraże"},
        "max_area":        {"value": max_area, "delta": None,                          "unit": "m² max",           "inverse": False, "group": "Metraże"},
        # Struktura
        "pct_agency":      {"value": pct_agency,  "delta": None,                       "unit": "% agencje",        "inverse": False, "group": "Struktura"},
        "pct_developer":   {"value": pct_dev,     "delta": None,                       "unit": "% deweloperzy",    "inverse": False, "group": "Struktura"},
        "pct_private":     {"value": pct_priv,    "delta": None,                       "unit": "% właściciele",    "inverse": False, "group": "Struktura"},
    }


def get_residential_kpis_with_deltas() -> dict:
    with get_conn() as conn:
        p_curr = conn.execute("""
            SELECT AVG(s.current_price_m2) as v FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='residential' AND l.transaction_type='sale'
              AND s.active_status=1 AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date >= date('now','-7 days')
        """).fetchone()
        p_prev = conn.execute("""
            SELECT AVG(s.current_price_m2) as v FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='residential' AND l.transaction_type='sale'
              AND s.active_status=1 AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date BETWEEN date('now','-37 days') AND date('now','-23 days')
        """).fetchone()
        ac = conn.execute("SELECT COUNT(*) as c FROM listings WHERE asset_class='residential' AND transaction_type='sale' AND is_active=1").fetchone()
        ac_p = conn.execute("""
            SELECT COUNT(DISTINCT s.offer_id) as c FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='residential' AND l.transaction_type='sale' AND s.active_status=1
              AND s.scrape_date BETWEEN date('now','-37 days') AND date('now','-23 days')
        """).fetchone()
        new7 = conn.execute("SELECT COUNT(*) as c FROM listings WHERE asset_class='residential' AND transaction_type='sale' AND first_seen >= date('now','-7 days')").fetchone()
        new14 = conn.execute("SELECT COUNT(*) as c FROM listings WHERE asset_class='residential' AND transaction_type='sale' AND first_seen BETWEEN date('now','-14 days') AND date('now','-8 days')").fetchone()
        del30 = conn.execute("SELECT COUNT(*) as c FROM listings WHERE asset_class='residential' AND transaction_type='sale' AND is_active=0 AND last_seen >= date('now','-30 days')").fetchone()

    pc = round(p_curr["v"], 0) if p_curr and p_curr["v"] else None
    pp = p_prev["v"] if p_prev else None
    active = ac["c"] if ac else 0
    active_p = ac_p["c"] if ac_p else None
    n7 = new7["c"] if new7 else 0
    n7p = new14["c"] if new14 else None
    d30 = del30["c"] if del30 else 0

    return {
        "median_price_m2": {"value": pc,     "delta": _mom_delta(pc, pp),          "unit": "PLN/m²",          "inverse": False},
        "active_listings": {"value": active, "delta": _mom_delta(active, active_p), "unit": "ofert aktywnych", "inverse": True},
        "new_listings_7d": {"value": n7,     "delta": _mom_delta(n7, n7p),          "unit": "nowych 7d",       "inverse": True},
        "absorbed_30d":    {"value": d30,    "delta": None,                          "unit": "zdjętych 30d",    "inverse": False},
        "price_reduction_pct": {"value": None, "delta": None,                        "unit": "% z obniżką",     "inverse": True},
    }


# ──────────────────────────────────────────────
# BUILDING HISTORY
# ──────────────────────────────────────────────

def get_building_history(building_name: str, days: int = 90) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT s.scrape_date,
                   AVG(s.current_price_m2) as avg_price_m2,
                   COUNT(*) as active_units,
                   SUM(l.area_m2) as total_area
            FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='office'
              AND LOWER(COALESCE(l.building_name,'')) = LOWER(:bname)
              AND s.active_status=1
              AND s.scrape_date >= date('now', :days)
            GROUP BY s.scrape_date
            ORDER BY s.scrape_date
        """, conn, params={"bname": building_name, "days": f"-{days} days"})
    return df


def get_building_units(building_name: str) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT offer_id, title, url, area_m2, price_total, price_per_m2,
                   building_class, advertiser_type, first_seen, is_active
            FROM listings
            WHERE asset_class='office'
              AND LOWER(COALESCE(building_name,'')) = LOWER(:bname)
              AND is_active=1
            ORDER BY price_per_m2
        """, conn, params={"bname": building_name})
    return df


# ──────────────────────────────────────────────
# DEVELOPERS TABLE
# ──────────────────────────────────────────────

def get_developers_table() -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT
                COALESCE(dp.developer, 'Nieznany') as developer,
                COUNT(DISTINCT dp.project_id) as active_projects,
                SUM(CASE WHEN l.is_active=1 THEN 1 ELSE 0 END) as available_units,
                AVG(CASE WHEN l.is_active=1 THEN l.price_per_m2 END) as avg_price_m2,
                COUNT(CASE WHEN l.is_active=0 AND l.last_seen >= date('now','-30 days') THEN 1 END) as sold_30d
            FROM developer_projects dp
            LEFT JOIN listings l ON l.parent_project_id=dp.project_id
              AND l.transaction_type='invest_unit'
            GROUP BY COALESCE(dp.developer, 'Nieznany')
            ORDER BY available_units DESC NULLS LAST
        """, conn)
    if not df.empty:
        df["velocity_per_day"] = (df["sold_30d"].fillna(0).astype(int) / 30).round(2)
    return df


def get_last_scrape_ts() -> str:
    with get_conn() as conn:
        r = conn.execute("SELECT MAX(run_ts) as ts FROM scrape_runs").fetchone()
    return r["ts"][:16].replace("T", " ") + " UTC" if r and r["ts"] else "—"


# ──────────────────────────────────────────────
# WATCHLIST
# ──────────────────────────────────────────────

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
                -- Aktualna cena (najnowszy snapshot)
                (SELECT s.current_price FROM snapshots s
                 WHERE s.offer_id = l.offer_id
                 ORDER BY s.scrape_ts DESC LIMIT 1) AS current_price,
                (SELECT s.current_price_m2 FROM snapshots s
                 WHERE s.offer_id = l.offer_id
                 ORDER BY s.scrape_ts DESC LIMIT 1) AS current_price_m2,
                -- Cena w momencie dodania do obserwacji (snapshot <= added_ts)
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
    # Policz deltę ceny od dodania
    df["price_change"] = df["current_price"] - df["price_at_add"]
    df["price_change_pct"] = (
        df["price_change"] / df["price_at_add"].replace(0, float("nan")) * 100
    ).round(1)
    return df
