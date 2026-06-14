"""
analytics/listings.py — Listing Intelligence Layer.
Agregaty i KPI dla rynku ofertowego (office + residential + developers + buildings).
"""

from typing import Optional
import pandas as pd

from database import get_conn, ZONE_MAP, COMPETITIVE_SET
from ._helpers import mom_delta


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


def get_competitive_position() -> pd.DataFrame:
    """Ocean Plaza vs konkurencja — agregat per budynek z competitive set.

    Per budynek: aktywne oferty, śr. czynsz PLN/m²/mc, dostępna powierzchnia,
    zmiana czynszu 30d, zmiana podaży 30d. Plus kolumna 'position' (gaining/losing/stable)
    porównująca dynamikę budynku z medianą reszty rynku biurowego.
    """
    with get_conn() as conn:
        rent_now = pd.read_sql_query("""
            SELECT building_name,
                   AVG(price_per_m2) as rent_now,
                   COUNT(*) as active_offers,
                   SUM(area_m2) as available_area
            FROM listings
            WHERE asset_class='office' AND is_active=1 AND building_name IS NOT NULL
            GROUP BY building_name
        """, conn)
        rent_prev = pd.read_sql_query("""
            SELECT l.building_name, AVG(s.current_price_m2) as rent_prev
            FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='office' AND l.building_name IS NOT NULL
              AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date BETWEEN date('now','-37 days') AND date('now','-23 days')
            GROUP BY l.building_name
        """, conn)
        supply_prev = pd.read_sql_query("""
            SELECT building_name,
                   COUNT(CASE WHEN first_seen <= date('now','-30 days') THEN 1 END) as offers_prev
            FROM listings
            WHERE asset_class='office' AND building_name IS NOT NULL
            GROUP BY building_name
        """, conn)

    from database import COMPETITIVE_SET

    def to_comp(name):
        if not name:
            return None
        nl = name.lower()
        for bname, kws in COMPETITIVE_SET.items():
            if any(kw in nl for kw in kws):
                return bname
        return None

    rent_now["comp"] = rent_now["building_name"].apply(to_comp)
    rent_now = rent_now[rent_now["comp"].notna()]
    if rent_now.empty:
        return pd.DataFrame()

    rent_prev["comp"] = rent_prev["building_name"].apply(to_comp)
    supply_prev["comp"] = supply_prev["building_name"].apply(to_comp)

    agg = rent_now.groupby("comp").agg(
        active_offers=("active_offers", "sum"),
        rent_now=("rent_now", "mean"),
        available_area=("available_area", "sum"),
    ).reset_index()
    rp = rent_prev[rent_prev["comp"].notna()].groupby("comp")["rent_prev"].mean().reset_index()
    sp = supply_prev[supply_prev["comp"].notna()].groupby("comp")["offers_prev"].sum().reset_index()
    agg = agg.merge(rp, on="comp", how="left").merge(sp, on="comp", how="left")

    agg["rent_chg_pct"] = ((agg["rent_now"] - agg["rent_prev"]) / agg["rent_prev"] * 100).round(1)
    agg["supply_chg"] = (agg["active_offers"] - agg["offers_prev"].fillna(0)).astype(int)

    # Pozycja konkurencyjna Ocean Plaza: niższy wzrost podaży + utrzymanie czynszu = gaining
    def position(row):
        rc = row["rent_chg_pct"]
        sc = row["supply_chg"]
        if pd.isna(rc):
            return "—"
        if rc >= 0 and sc <= 0:
            return "▲ gaining"
        if rc < -3 or sc > 3:
            return "▼ losing"
        return "● stable"

    agg["position"] = agg.apply(position, axis=1)
    agg = agg.rename(columns={"comp": "building"})
    # Ocean Plaza na górze
    agg["_op"] = agg["building"].apply(lambda b: 0 if "ocean" in b.lower() else 1)
    agg = agg.sort_values(["_op", "rent_now"], ascending=[True, False]).drop(columns="_op")
    return agg


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
    """Sales Velocity = liczba jednostek sprzedanych (delisted) w oknie czasowym."""
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


# ──────────────────────────────────────────────
# KPIs z deltami m/m
# ──────────────────────────────────────────────

def get_office_kpis_with_deltas() -> dict:
    with get_conn() as conn:
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

        prices_prev = conn.execute("""
            SELECT AVG(s.current_price_m2) as avg_p
            FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
            WHERE l.asset_class='office' AND s.active_status=1
              AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date BETWEEN date('now','-37 days') AND date('now','-23 days')
        """).fetchone()

        median_row = conn.execute("""
            SELECT price_per_m2 FROM listings
            WHERE asset_class='office' AND is_active=1 AND price_per_m2 IS NOT NULL
            ORDER BY price_per_m2
            LIMIT 1 OFFSET (
                SELECT COUNT(*)/2 FROM listings
                WHERE asset_class='office' AND is_active=1 AND price_per_m2 IS NOT NULL
            )
        """).fetchone()

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
        "avg_rent":        {"value": avg_p,    "delta": mom_delta(avg_p, prev_p),     "unit": "PLN/m²/mc śr.",    "inverse": False, "group": "Stawki"},
        "median_rent":     {"value": med_p,    "delta": None,                          "unit": "PLN/m²/mc med.",   "inverse": False, "group": "Stawki"},
        "min_rent":        {"value": min_p,    "delta": None,                          "unit": "PLN/m²/mc min",    "inverse": False, "group": "Stawki"},
        "max_rent":        {"value": max_p,    "delta": None,                          "unit": "PLN/m²/mc max",    "inverse": False, "group": "Stawki"},
        # Podaż
        "active_count":    {"value": active,   "delta": mom_delta(active, active_p),  "unit": "ofert aktywnych",  "inverse": True,  "group": "Podaż"},
        "total_space":     {"value": total_m2, "delta": None,                          "unit": "tys. m² łącznie",  "inverse": True,  "group": "Podaż"},
        "new_30d":         {"value": new,      "delta": mom_delta(new, new_p_v),      "unit": "nowych (30d)",     "inverse": True,  "group": "Podaż"},
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
        "median_price_m2": {"value": pc,     "delta": mom_delta(pc, pp),           "unit": "PLN/m²",          "inverse": False},
        "active_listings": {"value": active, "delta": mom_delta(active, active_p), "unit": "ofert aktywnych", "inverse": True},
        "new_listings_7d": {"value": n7,     "delta": mom_delta(n7, n7p),          "unit": "nowych 7d",       "inverse": True},
        "absorbed_30d":    {"value": d30,    "delta": None,                          "unit": "zdjętych 30d",    "inverse": False},
        "price_reduction_pct": {"value": None, "delta": None,                        "unit": "% z obniżką",     "inverse": True},
    }
