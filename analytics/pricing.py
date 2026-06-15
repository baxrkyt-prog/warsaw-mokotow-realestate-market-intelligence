"""
analytics/pricing.py — Pricing Intelligence Layer.

Łączy Listing Intelligence (asking) z Transaction Intelligence (transaction)
przez znormalizowaną geografię. Nigdy nie joinuje po ID ofert.

══════════════════════════════════════════════════════════════════
FORMUŁY (dokumentacja modelu)
══════════════════════════════════════════════════════════════════

SPREAD
    spread_pct = (median_tx_price_m2 − median_asking_price_m2) / median_asking_price_m2
    Ujemny = transakcje zamykają się PONIŻEJ cen ofertowych (normalny rynek).
    Negotiation Index = spread_pct (ta sama liczba, biznesowa nazwa).

DUAL-MODE materializacji:
    1. district-mode — granularne `transactions` per district_norm
       (≥3 transakcji w oknie; confidence wg analytics.confidence)
    2. city-benchmark-mode — agregaty NBP z transaction_market_snapshots
       (poziom Warszawy; zapis z district_norm='' i confidence='low',
        bo porównujemy asking-Mokotów z tx-całe-miasto)

LIQUIDITY SCORE (0–100, 4 składowe × 25 pkt) — wymaga granularnych transakcji:
    A. Transaction velocity = tx_count_w / max(new_listings_w, 1)
       ratio 0 → 0 pkt; ratio ≥ 1 → 25 pkt; liniowo
    B. Inventory turnover: days_of_inventory = active_listings / (tx_count_w / w)
       0 dni → 25 pkt; ≥ 300 dni → 0 pkt; liniowo malejąco
    C. Velocity trend = Δ% tx_count okno-do-okna
       −50% → 0; 0% → 12.5; +50% → 25; clamp
    D. Listings stability = |Δ% active_listings 30d|
       0% → 25; ≥50% → 0; clamp
    ≥80 STRONG | ≥60 STABLE | ≥40 CAUTION | <40 DISTRESSED

PRICING PRESSURE SCORE (0–100, 4 składowe × 25 pkt):
    A. Spread component: spread 0% → 25 pkt; ≤ −15% → 0 pkt; liniowo
    B. Price-cut ratio (listings z obniżką / aktywne): 0% → 25; ≥50% → 0
    C. Price change velocity: Δ% median asking 30d; +2% → 25; ≤ −5% → 0
    D. Transaction activity: tx_count_90d vs średnia 4 poprzednich okien 90d;
       ratio ≥ 1 → 25; 0 → 0
    ≥80 STRONG | ≥60 STABLE | ≥40 CAUTION | <40 DISTRESSED
══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from database import get_conn, upsert_pricing_spread
from .confidence import (
    confidence_level, winsorized_median, is_displayable, LOW, SUPPRESS,
)

WINDOWS = [30, 90, 180, 365]

_LABELS = [(80, "STRONG", "green"), (60, "STABLE", "gold"),
           (40, "CAUTION", "amber"), (0, "DISTRESSED", "red")]


def _label(score: float) -> tuple[str, str]:
    for thr, lab, col in _LABELS:
        if score >= thr:
            return lab, col
    return "DISTRESSED", "red"


def _clamp(v: float, lo: float = 0.0, hi: float = 25.0) -> float:
    return max(lo, min(hi, v))


# ──────────────────────────────────────────────
# MATERIALIZACJA pricing_spreads
# ──────────────────────────────────────────────

def materialize_pricing_spreads(snapshot_date: str | None = None,
                                windows: list[int] | None = None) -> dict:
    """Codzienny job (cron, po collectorach). Zwraca statystyki.

    district-mode: per (property_type, district_norm) z granularnych transactions.
    city-benchmark-mode: NBP (najnowszy kwartał) vs median asking całego zbioru
    listings danego property_type — zapis z district_norm=''.
    """
    snapshot_date = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    windows = windows or WINDOWS
    now = datetime.now(timezone.utc).isoformat()
    stats = {"district_rows": 0, "city_rows": 0, "skipped_suppress": 0}

    with get_conn() as conn:
        # Tylko oferty SPRZEDAŻY (sale + invest_unit). Najem (rent, ~200 PLN/m²/mc)
        # zatruwa spread vs ceny transakcyjne sprzedaży. Office w listings to wyłącznie
        # najem — Pricing Intelligence liczymy dla residential.
        asking_df = pd.read_sql_query("""
            SELECT asset_class as property_type, district_norm, subdistrict, price_per_m2
            FROM listings
            WHERE is_active = 1 AND price_per_m2 IS NOT NULL
              AND district_norm IS NOT NULL
              AND asset_class = 'residential'
              AND transaction_type IN ('sale', 'invest_unit')
        """, conn)

        tx_df = pd.read_sql_query("""
            SELECT property_type, district_norm, transaction_date, transaction_price_per_m2
            FROM transactions
            WHERE transaction_price_per_m2 IS NOT NULL
        """, conn)

    today = pd.Timestamp(snapshot_date)
    if not tx_df.empty:
        tx_df["transaction_date"] = pd.to_datetime(tx_df["transaction_date"])

    # ── district-mode ────────────────────────
    for window in windows:
        if tx_df.empty:
            break
        cutoff = today - pd.Timedelta(days=window)
        tx_w = tx_df[tx_df["transaction_date"] >= cutoff]
        for (ptype, dnorm), grp in tx_w.groupby(["property_type", "district_norm"]):
            if not dnorm:
                continue
            ask = asking_df[(asking_df["property_type"] == ptype)
                            & (asking_df["district_norm"] == dnorm)]["price_per_m2"]
            n_tx, n_ask = len(grp), len(ask)
            age_days = int((today - grp["transaction_date"].max()).days)
            conf = confidence_level(n_tx, age_days)
            if conf == SUPPRESS or n_ask < 3:
                stats["skipped_suppress"] += 1
                continue
            med_tx = winsorized_median(grp["transaction_price_per_m2"])
            med_ask = winsorized_median(ask)
            if not med_tx or not med_ask:
                continue
            spread = (med_tx - med_ask) / med_ask
            with get_conn() as conn:
                upsert_pricing_spread(conn, {
                    "snapshot_date": snapshot_date,
                    "property_type": ptype,
                    "district": None,
                    "subdistrict": None,
                    "district_norm": dnorm,
                    "window_days": window,
                    "asking_price_per_m2": round(med_ask, 2),
                    "transaction_price_per_m2": round(med_tx, 2),
                    "spread_pct": round(spread * 100, 2),
                    "negotiation_index": round(spread * 100, 2),
                    "n_listings": n_ask,
                    "n_transactions": n_tx,
                    "confidence": conf,
                    "computed_at": now,
                })
            stats["district_rows"] += 1

    # ── city-benchmark-mode (NBP) ────────────
    with get_conn() as conn:
        nbp = conn.execute("""
            SELECT snapshot_date, market_type, average_price_per_m2
            FROM transaction_market_snapshots
            WHERE source = 'nbp_barn' AND property_type = 'residential'
              AND market_type = 'secondary'
            ORDER BY snapshot_date DESC LIMIT 1
        """).fetchone()

    if nbp and nbp["average_price_per_m2"]:
        ask_all = asking_df[asking_df["property_type"] == "residential"]["price_per_m2"]
        if len(ask_all) >= 3:
            med_ask = winsorized_median(ask_all)
            tx_city = float(nbp["average_price_per_m2"])
            spread = (tx_city - med_ask) / med_ask
            with get_conn() as conn:
                upsert_pricing_spread(conn, {
                    "snapshot_date": snapshot_date,
                    "property_type": "residential",
                    "district": "Warszawa (NBP benchmark)",
                    "subdistrict": None,
                    "district_norm": "",          # sentinel city-level
                    "window_days": 0,             # 0 = benchmark kwartalny, nie okno
                    "asking_price_per_m2": round(med_ask, 2),
                    "transaction_price_per_m2": round(tx_city, 2),
                    "spread_pct": round(spread * 100, 2),
                    "negotiation_index": round(spread * 100, 2),
                    "n_listings": len(ask_all),
                    "n_transactions": None,
                    "confidence": LOW,            # asking-Mokotów vs tx-całe-miasto
                    "computed_at": now,
                })
            stats["city_rows"] += 1
            stats["nbp_quarter"] = nbp["snapshot_date"]

    return stats


# ──────────────────────────────────────────────
# ODCZYTY
# ──────────────────────────────────────────────

def get_pricing_kpis(property_type: str = "residential",
                     district_norm: str | None = None,
                     window_days: int = 90) -> dict:
    """Najświeższy zestaw spreadów. district_norm=None → agregacja po dzielnicach
    (mediana spreadów district-mode) + benchmark NBP osobno."""
    with get_conn() as conn:
        if district_norm:
            row = conn.execute("""
                SELECT * FROM pricing_spreads
                WHERE property_type=? AND district_norm=? AND window_days=?
                ORDER BY snapshot_date DESC LIMIT 1
            """, (property_type, district_norm, window_days)).fetchone()
            district_rows = [row] if row else []
        else:
            latest = conn.execute("""
                SELECT MAX(snapshot_date) d FROM pricing_spreads
                WHERE property_type=? AND window_days=?
            """, (property_type, window_days)).fetchone()
            district_rows = conn.execute("""
                SELECT * FROM pricing_spreads
                WHERE property_type=? AND window_days=? AND snapshot_date=?
                  AND district_norm != ''
            """, (property_type, window_days, latest["d"] if latest else None)).fetchall() \
                if latest and latest["d"] else []

        nbp_row = conn.execute("""
            SELECT * FROM pricing_spreads
            WHERE property_type=? AND district_norm='' AND window_days=0
            ORDER BY snapshot_date DESC LIMIT 1
        """, (property_type,)).fetchone()

    out = {
        "window_days": window_days,
        "district_norm": district_norm,
        "median_asking": None, "median_transaction": None,
        "spread_pct": None, "negotiation_index": None,
        "confidence": SUPPRESS, "n_districts": len(district_rows),
        "nbp_benchmark": None,
    }
    rows = [r for r in district_rows if r]
    if rows:
        df = pd.DataFrame([dict(r) for r in rows])
        out["median_asking"] = round(float(df["asking_price_per_m2"].median()), 0)
        out["median_transaction"] = round(float(df["transaction_price_per_m2"].median()), 0)
        out["spread_pct"] = round(float(df["spread_pct"].median()), 2)
        out["negotiation_index"] = out["spread_pct"]
        # confidence = najgorszy z district rows ważony — bierzemy najczęstszy
        out["confidence"] = df["confidence"].mode().iloc[0]
    if nbp_row:
        out["nbp_benchmark"] = {
            "asking": nbp_row["asking_price_per_m2"],
            "transaction": nbp_row["transaction_price_per_m2"],
            "spread_pct": nbp_row["spread_pct"],
            "snapshot_date": nbp_row["snapshot_date"],
        }
    return out


def get_spread_table(property_type: str = "residential",
                     window_days: int = 90) -> pd.DataFrame:
    """Spready per dzielnica, sort by largest negative spread."""
    with get_conn() as conn:
        latest = conn.execute("""
            SELECT MAX(snapshot_date) d FROM pricing_spreads
            WHERE property_type=? AND window_days=?
        """, (property_type, window_days)).fetchone()
        if not latest or not latest["d"]:
            return pd.DataFrame()
        df = pd.read_sql_query("""
            SELECT ps.district_norm, gd.display_name,
                   ps.asking_price_per_m2, ps.transaction_price_per_m2,
                   ps.spread_pct, ps.negotiation_index,
                   ps.n_listings, ps.n_transactions, ps.confidence
            FROM pricing_spreads ps
            LEFT JOIN geo_districts gd ON gd.district_norm = ps.district_norm
            WHERE ps.property_type=? AND ps.window_days=? AND ps.snapshot_date=?
              AND ps.district_norm != ''
            ORDER BY ps.spread_pct ASC
        """, conn, params=(property_type, window_days, latest["d"]))
    if not df.empty:
        df["display_name"] = df["display_name"].fillna(df["district_norm"])
    return df


def get_spread_history(property_type: str = "residential",
                       district_norm: str | None = None,
                       days: int = 365) -> pd.DataFrame:
    """Time-series spreadów do Historical Spread Analysis (per okno)."""
    dn_sql = "AND district_norm = :dn" if district_norm else "AND district_norm != ''"
    params = {"pt": property_type, "days": f"-{days} days"}
    if district_norm:
        params["dn"] = district_norm
    with get_conn() as conn:
        df = pd.read_sql_query(f"""
            SELECT snapshot_date, window_days,
                   AVG(spread_pct) as spread_pct,
                   AVG(asking_price_per_m2) as asking,
                   AVG(transaction_price_per_m2) as transaction_px
            FROM pricing_spreads
            WHERE property_type = :pt {dn_sql}
              AND window_days > 0
              AND snapshot_date >= date('now', :days)
            GROUP BY snapshot_date, window_days
            ORDER BY snapshot_date
        """, conn, params=params)
    return df


# ──────────────────────────────────────────────
# LIQUIDITY SCORE
# ──────────────────────────────────────────────

def compute_liquidity_score(property_type: str = "residential",
                            district_norm: str | None = None,
                            window_days: int = 30) -> dict:
    """0–100; formuła w docstringu modułu. Wymaga granularnych transakcji."""
    dn_tx = "AND district_norm = :dn" if district_norm else ""
    dn_li = "AND district_norm = :dn" if district_norm else ""
    params = {"pt": property_type, "w": f"-{window_days} days",
              "w2": f"-{window_days*2} days", "w2e": f"-{window_days+1} days"}
    if district_norm:
        params["dn"] = district_norm

    with get_conn() as conn:
        tx_now = conn.execute(f"""
            SELECT COUNT(*) c FROM transactions
            WHERE property_type=:pt {dn_tx}
              AND transaction_date >= date('now', :w)
        """, params).fetchone()["c"]
        tx_prev = conn.execute(f"""
            SELECT COUNT(*) c FROM transactions
            WHERE property_type=:pt {dn_tx}
              AND transaction_date BETWEEN date('now', :w2) AND date('now', :w2e)
        """, params).fetchone()["c"]
        # Tylko rynek sprzedaży — najem nie konkuruje z transakcjami sprzedaży
        ac_cls = "residential" if property_type == "residential" else property_type
        sale_types = "('sale', 'invest_unit')"
        active = conn.execute(f"""
            SELECT COUNT(*) c FROM listings
            WHERE asset_class=:pt AND is_active=1
              AND transaction_type IN {sale_types} {dn_li}
        """, {**params, "pt": ac_cls}).fetchone()["c"]
        new_w = conn.execute(f"""
            SELECT COUNT(*) c FROM listings
            WHERE asset_class=:pt AND first_seen >= date('now', :w)
              AND transaction_type IN {sale_types} {dn_li}
        """, {**params, "pt": ac_cls}).fetchone()["c"]
        active_prev = conn.execute(f"""
            SELECT COUNT(DISTINCT s.offer_id) c FROM snapshots s
            JOIN listings l ON l.offer_id = s.offer_id
            WHERE l.asset_class=:pt AND s.active_status=1
              AND l.transaction_type IN {sale_types}
              AND s.scrape_date BETWEEN date('now', :w2) AND date('now', :w2e)
              {'AND l.district_norm = :dn' if district_norm else ''}
        """, {**params, "pt": ac_cls}).fetchone()["c"]

    conf = confidence_level(tx_now)
    if not is_displayable(conf):
        return {"score": None, "label": "n/d", "color": "gray",
                "confidence": conf, "components": {},
                "reason": f"za mało transakcji w oknie ({tx_now} < 3)"}

    # A. Transaction velocity
    a = _clamp((tx_now / max(new_w, 1)) * 25)
    # B. Inventory turnover — preferuj realny median DOM (lifecycle); fallback: stock/sales rate.
    #    DOM 0d → 25 pkt, ≥300d → 0 pkt. DOM to bezpośrednia miara czasu na rynku.
    from .lifecycle import get_dom_stats
    dom = get_dom_stats(property_type if property_type in ("office", "residential") else "residential")
    if dom.get("real_dom") and dom.get("median_dom") is not None:
        days_inv = dom["median_dom"]
        dom_source = "median_dom"
    else:
        tx_per_day = tx_now / window_days
        days_inv = (active / tx_per_day) if tx_per_day > 0 else 300
        dom_source = "stock/sales"
    b = _clamp(25 - (days_inv / 300) * 25)
    # C. Velocity trend
    delta = (tx_now - tx_prev) / max(tx_prev, 1)
    c = _clamp(12.5 + delta * 25)
    # D. Listings stability
    chg = abs(active - active_prev) / max(active_prev, 1) if active_prev else 0.0
    d = _clamp(25 - chg * 50)

    score = round(a + b + c + d)
    label, color = _label(score)
    return {
        "score": score, "label": label, "color": color, "confidence": conf,
        "components": {
            "Transaction Velocity": round(a, 1),
            "Inventory Turnover":   round(b, 1),
            "Velocity Trend":       round(c, 1),
            "Listings Stability":   round(d, 1),
        },
        "inputs": {"tx_count": tx_now, "tx_prev": tx_prev,
                   "active_listings": active, "new_listings": new_w,
                   "days_of_inventory": round(days_inv, 1), "dom_source": dom_source},
    }


# ──────────────────────────────────────────────
# PRICING PRESSURE SCORE
# ──────────────────────────────────────────────

def compute_pricing_pressure_score(property_type: str = "residential",
                                   district_norm: str | None = None) -> dict:
    """0–100; formuła w docstringu modułu."""
    kpis = get_pricing_kpis(property_type, district_norm, window_days=90)
    spread = kpis["spread_pct"]
    spread_conf = kpis["confidence"]

    dn_li = "AND district_norm = :dn" if district_norm else ""
    params = {"pt": property_type}
    if district_norm:
        params["dn"] = district_norm

    with get_conn() as conn:
        ac = conn.execute(f"""
            SELECT COUNT(*) c FROM listings
            WHERE asset_class=:pt AND is_active=1 AND transaction_type='sale' {dn_li}
        """, params).fetchone()["c"]
        cuts = conn.execute(f"""
            SELECT COUNT(*) c FROM listings l
            WHERE l.asset_class=:pt AND l.transaction_type='sale' AND l.is_active=1 {dn_li}
              AND l.price_total < (
                  SELECT MAX(s.current_price) FROM snapshots s
                  WHERE s.offer_id = l.offer_id AND s.current_price IS NOT NULL
              )
        """, params).fetchone()["c"]
        ask_now = conn.execute(f"""
            SELECT AVG(s.current_price_m2) v FROM snapshots s
            JOIN listings l ON l.offer_id = s.offer_id
            WHERE l.asset_class=:pt AND l.transaction_type='sale' AND s.active_status=1
              AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date >= date('now','-7 days') {dn_li.replace('district_norm','l.district_norm')}
        """, params).fetchone()["v"]
        ask_prev = conn.execute(f"""
            SELECT AVG(s.current_price_m2) v FROM snapshots s
            JOIN listings l ON l.offer_id = s.offer_id
            WHERE l.asset_class=:pt AND l.transaction_type='sale' AND s.active_status=1
              AND s.current_price_m2 IS NOT NULL
              AND s.scrape_date BETWEEN date('now','-37 days') AND date('now','-23 days')
              {dn_li.replace('district_norm','l.district_norm')}
        """, params).fetchone()["v"]
        tx_90 = conn.execute(f"""
            SELECT COUNT(*) c FROM transactions
            WHERE property_type=:pt AND transaction_date >= date('now','-90 days')
              {dn_li}
        """, params).fetchone()["c"]
        tx_hist = conn.execute(f"""
            SELECT COUNT(*) c FROM transactions
            WHERE property_type=:pt
              AND transaction_date BETWEEN date('now','-450 days') AND date('now','-91 days')
              {dn_li}
        """, params).fetchone()["c"]

    # A. Spread component (brak spreadu → neutralne 12.5)
    if spread is not None:
        a = _clamp(25 + (spread / 15) * 25) if spread < 0 else 25.0
    else:
        a = 12.5
    # B. Price-cut ratio
    cut_ratio = cuts / max(ac, 1)
    b = _clamp(25 - cut_ratio * 50)
    # C. Price change velocity (30d)
    if ask_now and ask_prev and ask_prev > 0:
        chg = (ask_now - ask_prev) / ask_prev * 100
        c = _clamp(12.5 + (chg / 5) * 12.5 + (chg / 2) * 12.5 if chg >= 0
                   else 12.5 + (chg / 5) * 12.5)
        c = _clamp(c)
    else:
        c = 12.5
    # D. Transaction activity vs rolling history.
    # Brak JAKICHKOLWIEK danych transakcyjnych = brak sygnału, nie sygnał złej
    # aktywności → komponent neutralny (12.5), nie zerowy.
    hist_avg_90 = tx_hist / 4 if tx_hist else 0
    if tx_90 == 0 and tx_hist == 0:
        d = 12.5
    elif hist_avg_90 > 0:
        d = _clamp((tx_90 / hist_avg_90) * 25)
    else:
        d = _clamp(25.0 if tx_90 > 0 else 0.0)

    score = round(a + b + c + d)
    label, color = _label(score)
    return {
        "score": score, "label": label, "color": color,
        "confidence": spread_conf,
        "components": {
            "Spread":              round(a, 1),
            "Price-Cut Ratio":     round(b, 1),
            "Price Velocity":      round(c, 1),
            "Transaction Activity": round(d, 1),
        },
        "inputs": {"spread_pct": spread, "price_cut_ratio": round(cut_ratio * 100, 1),
                   "tx_90d": tx_90, "tx_hist_avg_90d": round(hist_avg_90, 1)},
    }
