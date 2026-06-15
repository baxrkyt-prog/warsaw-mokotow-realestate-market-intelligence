"""
pages/office.py — Office Market Module
6 widoków: Overview | Competition | Buildings | Map | Pipeline | Forecast
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from analytics import (
    get_office_summary, get_office_trend, get_competitive_set, get_competitive_position,
    get_office_zone_summary, get_office_forecast,
    compute_office_health_score, get_office_kpis_with_deltas,
    get_building_history, get_building_units,
    get_developer_projects, get_watchlist_ids,
)
from _ui import (
    inject_css, page_header, kpi_card, health_score_widget,
    section_header, divider, apply_plot_theme, listing_table, tracking_maturity_note,
    CLR_GOLD, CLR_OFFICE, CLR_ALERT, CLR_TEXT, CLR_MUTED, CLR_BORDER, CLR_SURFACE,
)

def _build_forecast_df(hist: pd.DataFrame, fcast: pd.DataFrame) -> pd.DataFrame:
    """Łączy hist+fcast w jeden DataFrame z kolumną 'type'."""
    parts = []
    if hist is not None and not hist.empty:
        h = hist[["scrape_date", "avg_price_m2"]].copy()
        h.columns = ["date", "value"]
        h["type"] = "historical"
        parts.append(h)
    if fcast is not None and not fcast.empty and "date" in fcast.columns:
        f = fcast.copy()
        f["type"] = "forecast"
        parts.append(f)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


st.set_page_config(
    page_title="Office Market · Ocean Plaza MI",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()

# ── nawigacja wstecz ──────────────────────────
if st.button("← Home", key="back_home"):
    st.switch_page("app.py")

page_header("Office Market", "Mokotów · biura na wynajem", color=CLR_OFFICE)
tracking_maturity_note()

# ── wczytaj dane ─────────────────────────────
@st.cache_data(ttl=300)
def load_data():
    summary  = get_office_summary()
    trend    = get_office_trend(90)
    compset  = get_competitive_set()
    zones    = get_office_zone_summary()
    _off_hist, _off_fcast = get_office_forecast(60)
    forecast = _build_forecast_df(_off_hist, _off_fcast)
    health   = compute_office_health_score()
    kpis     = get_office_kpis_with_deltas()
    return summary, trend, compset, zones, forecast, health, kpis

try:
    summary, trend, compset, zones, forecast, health, kpis = load_data()
    data_ok = True
except Exception as e:
    st.error(f"Błąd ładowania danych: {e}")
    data_ok = False
    summary = trend = compset = zones = forecast = health = kpis = None

# ──────────────────────────────────────────────
# TABS
# ──────────────────────────────────────────────
tabs = st.tabs(["Overview", "Listings", "Competition", "Buildings", "Map", "Pipeline", "Forecast", "Delisted"])

# ── TAB 0: OVERVIEW ───────────────────────────
with tabs[0]:
    if not data_ok:
        st.info("Brak danych — uruchom scraper_office.py")
    else:
        # ── Health Score + trend inline ───────────────────────────────
        hs_col, tr_col = st.columns([1, 2])
        with hs_col:
            section_header("Market Health Score")
            health_score_widget(health, CLR_OFFICE)

        with tr_col:
            section_header("Trend stawek", "Avg PLN/m²/mc — 90 dni")
            if trend is not None and not trend.empty:
                fig_tr = go.Figure()
                fig_tr.add_trace(go.Scatter(
                    x=trend["scrape_date"], y=trend["avg_price_m2"],
                    mode="lines+markers", fill="tozeroy",
                    fillcolor=f"rgba(74,143,181,0.12)",
                    line=dict(color=CLR_OFFICE, width=2), marker=dict(size=4),
                ))
                apply_plot_theme(fig_tr)
                fig_tr.update_layout(margin=dict(l=30, r=10, t=10, b=30), height=160)
                st.plotly_chart(fig_tr, use_container_width=True)
            else:
                st.info("Zbierz więcej snapshotów.")

        divider()

        # ── SEKCJA 1: STAWKI ─────────────────────────────────────────
        section_header("Stawki czynszowe", "PLN/m²/mc — oferty aktywne")
        r1, r2, r3, r4 = st.columns(4)
        for col, key, label in [
            (r1, "avg_rent",    "Średnia"),
            (r2, "median_rent", "Mediana"),
            (r3, "min_rent",    "Minimum"),
            (r4, "max_rent",    "Maximum"),
        ]:
            d = kpis.get(key, {})
            with col:
                kpi_card(label, d.get("value"), unit=d.get("unit",""), delta=d.get("delta"))
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        # Rozkład cen — histogram inline
        @st.cache_data(ttl=300)
        def _office_price_dist():
            from database import get_conn as _gc
            import pandas as _pd
            with _gc() as conn:
                return _pd.read_sql_query("""
                    SELECT price_per_m2, area_m2, advertiser_type, building_name
                    FROM listings
                    WHERE asset_class='office' AND is_active=1
                      AND price_per_m2 IS NOT NULL AND price_per_m2 > 0
                """, conn)
        dist_df = _office_price_dist()

        if not dist_df.empty:
            d1, d2 = st.columns(2)
            with d1:
                fig_h = go.Figure(go.Histogram(
                    x=dist_df["price_per_m2"], nbinsx=20,
                    marker_color=CLR_OFFICE, opacity=0.8,
                ))
                fig_h.update_layout(
                    xaxis_title="PLN/m²/mc", yaxis_title="Liczba ofert",
                    bargap=0.04, height=220, margin=dict(l=30,r=10,t=10,b=30),
                )
                apply_plot_theme(fig_h)
                st.plotly_chart(fig_h, use_container_width=True)
            with d2:
                # Box per advertiser_type
                fig_box = go.Figure()
                colors_adv = {"agency": CLR_OFFICE, "developer": CLR_GOLD, "private": "#7a7f8e"}
                for adv, grp in dist_df.groupby("advertiser_type"):
                    fig_box.add_trace(go.Box(
                        y=grp["price_per_m2"], name=adv,
                        marker_color=colors_adv.get(adv, CLR_MUTED),
                        boxmean=True, width=0.4,
                    ))
                fig_box.update_layout(
                    yaxis_title="PLN/m²/mc", showlegend=True,
                    height=220, margin=dict(l=30,r=10,t=10,b=30),
                )
                apply_plot_theme(fig_box)
                st.plotly_chart(fig_box, use_container_width=True)

        divider()

        # ── SEKCJA 2: PODAŻ ──────────────────────────────────────────
        section_header("Podaż", "Stan aktywnych ofert")
        s1, s2, s3, s4 = st.columns(4)
        for col, key, label in [
            (s1, "active_count", "Aktywnych ofert"),
            (s2, "total_space",  "Łączna pow."),
            (s3, "new_30d",      "Nowych (30d)"),
            (s4, "absorbed_30d", "Zdjętych (30d)"),
        ]:
            d = kpis.get(key, {})
            with col:
                kpi_card(label, d.get("value"), unit=d.get("unit",""),
                         delta=d.get("delta"), inverse=d.get("inverse", False))
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        divider()

        # ── SEKCJA 3: METRAŻE ────────────────────────────────────────
        section_header("Metraże", "Rozkład powierzchni aktywnych ofert")
        m1, m2, m3, m4 = st.columns(4)
        for col, key, label in [
            (m1, "avg_area",    "Średnia pow."),
            (m2, "median_area", "Mediana pow."),
            (m3, "min_area",    "Min pow."),
            (m4, "max_area",    "Max pow."),
        ]:
            d = kpis.get(key, {})
            with col:
                kpi_card(label, d.get("value"), unit=d.get("unit",""))

        if not dist_df.empty:
            fig_area = go.Figure(go.Histogram(
                x=dist_df["area_m2"].dropna(), nbinsx=25,
                marker_color=CLR_GOLD, opacity=0.8,
            ))
            fig_area.update_layout(
                xaxis_title="m²", yaxis_title="Liczba ofert",
                bargap=0.04, height=200, margin=dict(l=30,r=10,t=10,b=30),
            )
            apply_plot_theme(fig_area)
            st.plotly_chart(fig_area, use_container_width=True)

        divider()

        # ── SEKCJA 4: STRUKTURA ───────────────────────────────────────
        section_header("Struktura ofert")
        st1, st2, st3, st4 = st.columns(4)
        for col, key, label in [
            (st1, "pct_agency",    "Agencje"),
            (st2, "pct_developer", "Deweloperzy"),
            (st3, "pct_private",   "Właściciele"),
        ]:
            d = kpis.get(key, {})
            with col:
                kpi_card(label, d.get("value"), unit=d.get("unit",""))

        if not dist_df.empty and "advertiser_type" in dist_df.columns:
            adv_counts = dist_df["advertiser_type"].value_counts()
            with st4:
                fig_pie = go.Figure(go.Pie(
                    labels=adv_counts.index.tolist(),
                    values=adv_counts.values.tolist(),
                    hole=0.5,
                    marker_colors=[{"agency": CLR_OFFICE, "developer": CLR_GOLD,
                                    "private": CLR_MUTED}.get(l, "#555") for l in adv_counts.index],
                ))
                fig_pie.update_layout(
                    showlegend=False, height=120,
                    margin=dict(l=0, r=0, t=0, b=0),
                )
                apply_plot_theme(fig_pie)
                st.plotly_chart(fig_pie, use_container_width=True)

# ── TAB 1: LISTINGS ───────────────────────────
with tabs[1]:
    section_header("Wszystkie oferty biurowe", "Aktywne oferty — kliknij link aby otworzyć na Otodom")

    @st.cache_data(ttl=120)
    def load_office_listings():
        from database import get_conn as _gc
        import pandas as _pd
        with _gc() as conn:
            return _pd.read_sql_query("""
                SELECT offer_id, title, url, subdistrict, building_name, building_class,
                       area_m2, price_total, price_per_m2, advertiser_type,
                       first_seen, last_seen, is_active
                FROM listings
                WHERE asset_class = 'office' AND is_active = 1
                ORDER BY price_per_m2 DESC
            """, conn)

    off_listings = load_office_listings()
    watched_off  = get_watchlist_ids()

    if off_listings.empty:
        st.info("Brak ofert biurowych — uruchom scraper_office.py")
    else:
        # Filtry
        fc1, fc2, fc3 = st.columns([1, 1, 2])
        with fc1:
            subs = ["Wszystkie"] + sorted(off_listings["subdistrict"].dropna().unique().tolist())
            sub_f = st.selectbox("Dzielnica", subs, key="off_sub_f")
        with fc2:
            bld_names = ["Wszystkie"] + sorted(off_listings["building_name"].dropna().unique().tolist())
            bld_f = st.selectbox("Budynek", bld_names, key="off_bld_f")
        with fc3:
            area_min, area_max = int(off_listings["area_m2"].min() or 0), int(off_listings["area_m2"].max() or 9999)
            area_range = st.slider("Powierzchnia m²", area_min, area_max, (area_min, area_max), key="off_area_f")

        fil = off_listings.copy()
        if sub_f != "Wszystkie":
            fil = fil[fil["subdistrict"] == sub_f]
        if bld_f != "Wszystkie":
            fil = fil[fil["building_name"] == bld_f]
        fil = fil[(fil["area_m2"] >= area_range[0]) & (fil["area_m2"] <= area_range[1])]

        st.caption(f"Wyświetlono {len(fil)} z {len(off_listings)} ofert")
        listing_table(
            fil, key="off_listings",
            watched_ids=watched_off,
            show_cols=["⭐ Obserwuj", "offer_id", "title", "url", "subdistrict",
                       "building_name", "building_class", "area_m2",
                       "price_total", "price_per_m2", "Δ cena", "advertiser_type", "first_seen"],
        )

# ── TAB 2: COMPETITION ────────────────────────
with tabs[2]:
    section_header("Ocean Plaza vs Market",
                   "Pozycja konkurencyjna względem Curtis Plaza, New City, Marynarska BP")

    cpos = get_competitive_position()
    if cpos is None or cpos.empty:
        st.info("Brak danych competitive set — za mało ofert z rozpoznanym budynkiem.")
    else:
        # Tabela pozycji konkurencyjnej z interpretacją
        disp = cpos.copy()

        def pos_emoji(p):
            return p

        disp["Czynsz PLN/m²/mc"] = disp["rent_now"].round(0)
        disp["Zmiana czynszu"] = disp["rent_chg_pct"].apply(
            lambda v: f"{v:+.1f}%" if pd.notna(v) else "—")
        disp["Aktywne oferty"] = disp["active_offers"]
        disp["Zmiana podaży 30d"] = disp["supply_chg"].apply(lambda v: f"{v:+d}")
        disp["Dostępna pow. m²"] = disp["available_area"].round(0)
        disp["Pozycja"] = disp["position"]
        disp["Budynek"] = disp["building"]

        # Lifecycle: Median DOM + Turnover per budynek (które leasują się szybciej)
        from analytics import get_building_lifecycle
        blc = get_building_lifecycle()
        if not blc.empty:
            disp = disp.merge(
                blc[["building", "median_dom", "turnover_pct"]], on="building", how="left")
            disp["Median DOM"] = disp["median_dom"].apply(
                lambda v: f"{v:.0f} dni" if pd.notna(v) else "—")
            disp["Turnover"] = disp["turnover_pct"].apply(
                lambda v: f"{v:.0f}%" if pd.notna(v) else "—")
            cols = ["Budynek", "Czynsz PLN/m²/mc", "Zmiana czynszu", "Aktywne oferty",
                    "Median DOM", "Turnover", "Zmiana podaży 30d", "Pozycja"]
        else:
            cols = ["Budynek", "Czynsz PLN/m²/mc", "Zmiana czynszu", "Aktywne oferty",
                    "Zmiana podaży 30d", "Dostępna pow. m²", "Pozycja"]

        st.dataframe(disp[cols], use_container_width=True, hide_index=True)
        st.caption("Median DOM = ile dni oferty wiszą na rynku · Turnover = % zdjętych w 30d. "
                   "Niższy DOM + wyższy turnover = budynek leasuje się szybciej.")

        # Interpretacja pozycji Ocean Plaza
        op = cpos[cpos["building"].str.lower().str.contains("ocean")]
        if not op.empty:
            op_row = op.iloc[0]
            pos = op_row["position"]
            if "gaining" in pos:
                msg, color = "Ocean Plaza umacnia pozycję konkurencyjną — czynsz stabilny/rosnący przy nierosnącej podaży.", CLR_RESI
            elif "losing" in pos:
                msg, color = "Ocean Plaza traci pozycję — spadek czynszu lub rosnąca własna podaż względem rynku.", CLR_ALERT
            else:
                msg, color = "Ocean Plaza utrzymuje stabilną pozycję względem konkurencji.", CLR_GOLD
            st.markdown(f"""
            <div style="background:{CLR_SURFACE};border-left:3px solid {color};border-radius:6px;
                        padding:12px 18px;margin-top:12px;font-size:13px;color:{CLR_TEXT};">
                <b style="color:{color};">{pos}</b> — {msg}
            </div>
            """, unsafe_allow_html=True)

        divider()
        section_header("Porównanie stawek czynszu")
        fig = go.Figure(go.Bar(
            x=cpos["building"], y=cpos["rent_now"],
            marker_color=[CLR_GOLD if "ocean" in b.lower() else CLR_OFFICE
                          for b in cpos["building"]],
            text=cpos["rent_now"].round(0), textposition="outside",
        ))
        fig.update_layout(xaxis_title="", yaxis_title="PLN/m²/mc")
        apply_plot_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

# ── TAB 3: BUILDINGS ──────────────────────────
with tabs[3]:
    section_header("Building Profile", "Wybierz budynek aby zobaczyć szczegóły")

    @st.cache_data(ttl=300)
    def get_building_names():
        import sqlite3
        from database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT DISTINCT building_name FROM listings
            WHERE asset_class='office' AND is_active=1 AND building_name IS NOT NULL
            ORDER BY building_name
        """).fetchall()
        conn.close()
        return [r["building_name"] for r in rows]

    buildings = get_building_names()
    if not buildings:
        st.info("Brak danych budynków — uruchom scraper_office.py")
    else:
        selected = st.selectbox("Budynek", buildings)
        if selected:
            col_hist, col_units = st.columns([1, 1])
            with col_hist:
                section_header("Historia stawek i dostępności")
                hist = get_building_history(selected, 90)
                if hist is not None and not hist.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=hist["scrape_date"], y=hist["avg_price_m2"],
                        name="Avg PLN/m²", line=dict(color=CLR_OFFICE, width=2),
                    ))
                    apply_plot_theme(fig)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Brak historii dla tego budynku.")

            with col_units:
                section_header("Aktywne powierzchnie")
                units = get_building_units(selected)
                if units is not None and not units.empty:
                    watched = get_watchlist_ids()
                    listing_table(
                        units, key=f"bld_{selected}",
                        watched_ids=watched,
                        show_cols=["⭐ Obserwuj", "offer_id", "title", "url",
                                   "area_m2", "price_per_m2", "price_total", "Δ cena", "advertiser_type"],
                    )
                else:
                    st.info("Brak aktywnych ofert dla tego budynku.")

# ── TAB 4: MAP ────────────────────────────────
with tabs[4]:
    section_header("Mapa Mokotowa", "Aktywne oferty biurowe według dzielnicy")
    if zones is None or zones.empty:
        st.info("Brak danych strefowych.")
    else:
        st.dataframe(
            zones.rename(columns={
                "subdistrict": "Dzielnica",
                "active_count": "Aktywne oferty",
                "avg_price_m2": "Avg PLN/m²",
                "total_area_m2": "Łączna pow. m²",
            }),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("Mapa interaktywna wymaga danych geolokalizacji (adresów) — w kolejnym etapie.")

# ── TAB 5: PIPELINE ───────────────────────────
with tabs[5]:
    section_header("Pipeline biurowy", "Nowe projekty biurowe w Mokotowie")
    st.info("Dane pipeline'u biurowego będą pobierane z CBRE/JLL publikacji lub Otodom Komercyjne. Funkcja w kolejnym etapie.")

# ── TAB 6: FORECAST ───────────────────────────
with tabs[6]:
    section_header("Prognoza stawek", "Trend liniowy + 95% CI — 60 dni")
    if forecast is None or forecast.empty:
        st.info("Za mało danych do prognozy (wymagane min. 7 snapshotów).")
    else:
        fig = go.Figure()
        hist_mask = forecast["type"] == "historical"
        fore_mask = forecast["type"] == "forecast"

        fig.add_trace(go.Scatter(
            x=forecast.loc[hist_mask, "date"],
            y=forecast.loc[hist_mask, "value"],
            name="Historyczne", mode="lines+markers",
            line=dict(color=CLR_OFFICE, width=2),
        ))
        fig.add_trace(go.Scatter(
            x=forecast.loc[fore_mask, "date"],
            y=forecast.loc[fore_mask, "value"],
            name="Prognoza", mode="lines",
            line=dict(color=CLR_GOLD, width=2, dash="dash"),
        ))
        if "upper" in forecast.columns and "lower" in forecast.columns:
            fore_df = forecast.loc[fore_mask]
            fig.add_trace(go.Scatter(
                x=pd.concat([fore_df["date"], fore_df["date"].iloc[::-1]]),
                y=pd.concat([fore_df["upper"], fore_df["lower"].iloc[::-1]]),
                fill="toself", fillcolor="rgba(201,168,76,0.12)",
                line=dict(color="rgba(0,0,0,0)"), name="95% CI",
            ))
        apply_plot_theme(fig)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Model: regresja liniowa na historii snapshotów. Nie stanowi porady inwestycyjnej.")

# ── TAB 7: DELISTED ───────────────────────────
with tabs[7]:
    from analytics import get_delisting_kpis, get_delisting_trend
    section_header("Delisted Offices", "biura zdjęte z rynku — sygnał absorpcji powierzchni")
    dk = get_delisting_kpis("office")
    dc = st.columns(4)
    with dc[0]: kpi_card("Delisted 7d", dk["d7"], "ofert")
    with dc[1]: kpi_card("Delisted 30d", dk["d30"], "ofert", delta=dk["velocity_delta_pct"], inverse=True)
    with dc[2]: kpi_card("Delisted 90d", dk["d90"], "ofert")
    with dc[3]: kpi_card("Tempo", dk["velocity_per_day_30"], "ofert/dzień")

    divider()
    section_header("Trend delistingu", "miesięcznie, ostatnie 180 dni")
    tr = get_delisting_trend("office", bucket="monthly", days=180)
    if tr.empty:
        st.caption("Brak danych delistingu.")
    else:
        fig = go.Figure(go.Bar(x=tr["period"], y=tr["delisted"], marker_color=CLR_ALERT))
        fig.update_layout(height=300, yaxis_title="delisted")
        apply_plot_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

    divider()
    section_header("Tabela delisted", "ostatnia znana stawka + DOM w momencie zniknięcia")
    from database import get_conn as _gc
    with _gc() as _conn:
        deli = pd.read_sql_query("""
            SELECT title, building_name, last_known_price_per_m2,
                   dom_days(COALESCE(published_date, first_seen), delisted_date) AS dom,
                   delisted_date
            FROM listings
            WHERE asset_class='office' AND is_active=0 AND delisted_date IS NOT NULL
            ORDER BY delisted_date DESC LIMIT 200
        """, _conn)
    if deli.empty:
        st.caption("Brak delisted ofert biurowych.")
    else:
        d = deli.copy()
        d["Stawka PLN/m²/mc"] = d["last_known_price_per_m2"].round(0)
        d["DOM (dni)"] = d["dom"]
        d["Budynek"] = d["building_name"].fillna("—")
        d["Oferta"] = d["title"].fillna("—").str.slice(0, 45)
        d = d[["Oferta", "Budynek", "Stawka PLN/m²/mc", "DOM (dni)", "delisted_date"]]
        d.columns = ["Oferta", "Budynek", "Stawka PLN/m²/mc", "DOM (dni)", "Delisted"]
        st.dataframe(d, use_container_width=True, hide_index=True, height=400)
