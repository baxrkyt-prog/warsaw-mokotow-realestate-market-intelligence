"""
pages/residential.py — Residential Module
5 widoków: Market | Developers | Projects | Map | Forecast
+ Project Profile drill-down
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd


def _get_project_units_full(project_id: str) -> pd.DataFrame:
    import sqlite3
    from database import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT offer_id, title, url, area_m2, rooms, floor,
               price_total, price_per_m2, is_active
        FROM listings
        WHERE parent_project_id = ? AND transaction_type = 'invest_unit'
        ORDER BY rooms, area_m2
    """, (project_id,)).fetchall()
    conn.close()
    return pd.DataFrame([dict(r) for r in rows])


def _build_forecast_df(hist: pd.DataFrame, fcast: pd.DataFrame) -> pd.DataFrame:
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


from analytics import (
    get_residential_summary, get_residential_trend, get_residential_zone_summary,
    get_residential_forecast, get_developer_projects, get_project_snapshots,
    get_invest_units_summary, get_sales_velocity,
    compute_residential_health_score, get_residential_kpis_with_deltas,
    get_developers_table, get_watchlist_ids,
    get_pricing_kpis, get_transaction_kpis, compute_liquidity_score,
    compute_project_health_score,
)
from _ui import (
    inject_css, page_header, kpi_card, health_score_widget,
    section_header, divider, apply_plot_theme, listing_table,
    CLR_GOLD, CLR_RESI, CLR_OFFICE, CLR_ALERT, CLR_TEXT, CLR_MUTED, CLR_BORDER,
)

st.set_page_config(
    page_title="Residential · Ocean Plaza MI",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()

if st.button("← Home", key="back_home"):
    st.switch_page("app.py")

# ── Project Profile drill-down ────────────────
if "project_id" in st.query_params:
    pid = st.query_params["project_id"]
    _back = st.button("← Powrót do Residential")
    if _back:
        st.query_params.clear()
        st.rerun()

    @st.cache_data(ttl=300)
    def _load_project(project_id):
        projs = get_developer_projects()
        proj  = projs[projs["project_id"] == project_id] if not projs.empty else pd.DataFrame()
        snaps = get_project_snapshots(project_id, 90)
        units = _get_project_units_full(project_id)
        return proj, snaps, units

    proj_df, snap_df, units_df = _load_project(pid)

    # ── Nagłówek z nazwą projektu ─────────────────
    proj_name = proj_df.iloc[0]["name"] if not proj_df.empty else pid
    page_header(proj_name, "Project Profile", color=CLR_RESI)

    # ── Meta projektu (kompaktowo) ────────────────
    if not proj_df.empty:
        row = proj_df.iloc[0]
        st.markdown(
            f'<div style="font-size:12px;color:{CLR_MUTED};margin-bottom:14px;">'
            f'<b style="color:{CLR_TEXT};">{row.get("developer") or "—"}</b> · '
            f'{row.get("subdistrict") or "—"} · {(row.get("address") or "—")[:40]} · '
            f'śledzony od {str(row.get("first_seen","—"))[:10]}</div>',
            unsafe_allow_html=True)

    active_u = units_df[units_df["is_active"] == 1] if (units_df is not None and not units_df.empty) else pd.DataFrame()

    # ── 1. PROJECT HEALTH SCORE + składowe ────────
    try:
        phs = compute_project_health_score(pid)
    except Exception:
        phs = None

    if phs:
        hc1, hc2 = st.columns([1, 2.4])
        with hc1:
            health_score_widget(
                {"score": phs["score"], "label": phs["label"],
                 "components": phs["components"]},
                CLR_RESI,
            )
        with hc2:
            section_header("Składowe oceny projektu",
                           "Pricing · Velocity · Inventory · Transaction Context")
            comp = phs["components"]
            notes = phs["notes"]
            pc = st.columns(4)
            with pc[0]:
                kpi_card("Pricing", comp["Pricing"], unit="/25 pkt")
            with pc[1]:
                kpi_card("Velocity", comp["Velocity"], unit="/25 pkt")
            with pc[2]:
                kpi_card("Inventory", comp["Inventory"], unit="/25 pkt")
            with pc[3]:
                kpi_card("Tx Context", comp["Tx Context"], unit="/25 pkt")
            st.caption(
                f"Sprzedane 30d: {notes['sold_30d']} · Aktywne: {notes['active_units']} · "
                f"Sell-through: {notes['sell_through_pct'] if notes['sell_through_pct'] is not None else 'n/d'}% · "
                f"{notes['tx_context']}")
        divider()

    # ── 1b. LIFECYCLE projektu (DOM / turnover) ───
    try:
        from analytics import get_project_lifecycle
        plc = get_project_lifecycle(pid)
    except Exception:
        plc = None
    if plc and plc["active"]:
        section_header("Lifecycle projektu", "tempo rotacji jednostek")
        lc = st.columns(4)
        with lc[0]: kpi_card("Median DOM", plc["median_dom"], unit="dni na rynku")
        with lc[1]: kpi_card("Nowe (30d)", plc["new_30"], unit="jednostek")
        with lc[2]: kpi_card("Sprzedane (30d)", plc["delisted_30"], unit="jednostek")
        with lc[3]: kpi_card("Turnover", plc["turnover_pct"], unit="% / 30d")
        divider()

    # ── 2. KLUCZOWE KPI ───────────────────────────
    if not active_u.empty:
        ku1, ku2, ku3, ku4 = st.columns(4)
        with ku1: kpi_card("Dostępne jednostki", len(active_u), unit="mieszkań")
        with ku2: kpi_card("Median cena/m²", round(active_u["price_per_m2"].median()) if not active_u.empty else None, unit="PLN/m²")
        with ku3: kpi_card("Min cena", round((active_u["price_total"].min() or 0)/1000), unit="tys. PLN")
        with ku4: kpi_card("Max cena", round((active_u["price_total"].max() or 0)/1000), unit="tys. PLN")
        divider()

    # ── 3. TRZY KLUCZOWE TRENDY ───────────────────
    section_header("Kluczowe trendy", "Inventory · Median Price · Sales Velocity")
    if snap_df is not None and not snap_df.empty and len(snap_df) >= 2:
        t1, t2, t3 = st.columns(3, gap="large")
        with t1:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{CLR_TEXT};margin-bottom:4px;">Inventory Trend</div>', unsafe_allow_html=True)
            f1 = go.Figure(go.Scatter(
                x=snap_df["scrape_date"], y=snap_df["units_available"],
                mode="lines+markers", line=dict(color=CLR_RESI, width=2), fill="tozeroy"))
            f1.update_layout(height=240, yaxis_title="dostępne")
            st.plotly_chart(apply_plot_theme(f1), use_container_width=True)
        with t2:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{CLR_TEXT};margin-bottom:4px;">Median Price Trend</div>', unsafe_allow_html=True)
            f2 = go.Figure(go.Scatter(
                x=snap_df["scrape_date"], y=snap_df["median_price_m2"],
                mode="lines+markers", line=dict(color=CLR_GOLD, width=2)))
            f2.update_layout(height=240, yaxis_title="PLN/m²")
            st.plotly_chart(apply_plot_theme(f2), use_container_width=True)
        with t3:
            st.markdown(f'<div style="font-size:12px;font-weight:600;color:{CLR_TEXT};margin-bottom:4px;">Sales Velocity Trend</div>', unsafe_allow_html=True)
            # Velocity = ubytek dostępnych jednostek między snapshotami (sprzedane/okres)
            sv = snap_df.copy()
            sv["sold"] = (-sv["units_available"].diff()).clip(lower=0).fillna(0)
            f3 = go.Figure(go.Bar(x=sv["scrape_date"], y=sv["sold"], marker_color=CLR_OFFICE))
            f3.update_layout(height=240, yaxis_title="sprzedane/okres")
            st.plotly_chart(apply_plot_theme(f3), use_container_width=True)
    else:
        st.info("Za mało historii snapshotów do wykresów trendów (potrzeba ≥2 dni danych).")

    divider()

    # ── 4. ADVANCED ANALYTICS (collapsible) ───────
    if not active_u.empty:
        colors_rooms = {1: "#e05c5c", 2: "#e0924a", 3: CLR_GOLD, 4: CLR_RESI, 5: "#4a8fb5"}
        with st.expander("📊 Advanced Analytics — rozkłady, scatter, struktura pokoi", expanded=False):
            section_header("Scatter: metraż vs cena/m²")
            fig2 = go.Figure()
            for r, grp in active_u.groupby("rooms"):
                fig2.add_trace(go.Scatter(
                    x=grp["area_m2"], y=grp["price_per_m2"], mode="markers",
                    name=f"{int(r) if r else '?'} pok." if r else "?",
                    marker=dict(size=8, color=colors_rooms.get(int(r) if r else 0, CLR_MUTED), opacity=0.8),
                    text=grp["title"].str.replace(r".*—\s*", "", regex=True),
                    hovertemplate="<b>%{text}</b><br>%{x:.0f} m² · %{y:,.0f} PLN/m²<extra></extra>",
                ))
            fig2.update_layout(xaxis_title="Powierzchnia m²", yaxis_title="PLN/m²")
            apply_plot_theme(fig2)
            st.plotly_chart(fig2, use_container_width=True)

            h1, h2 = st.columns(2)
            with h1:
                section_header("Rozkład cen (PLN/m²)")
                fig3 = go.Figure(go.Histogram(x=active_u["price_per_m2"].dropna(),
                                              nbinsx=15, marker_color=CLR_RESI, opacity=0.8))
                fig3.update_layout(xaxis_title="PLN/m²", yaxis_title="Liczba jedn.", bargap=0.05)
                apply_plot_theme(fig3)
                st.plotly_chart(fig3, use_container_width=True)
            with h2:
                section_header("Rozkład metraży (m²)")
                fig4 = go.Figure(go.Histogram(x=active_u["area_m2"].dropna(),
                                              nbinsx=15, marker_color=CLR_GOLD, opacity=0.8))
                fig4.update_layout(xaxis_title="m²", yaxis_title="Liczba jedn.", bargap=0.05)
                apply_plot_theme(fig4)
                st.plotly_chart(fig4, use_container_width=True)

            section_header("Struktura oferty wg liczby pokoi")
            rooms_cnt = active_u["rooms"].value_counts().sort_index()
            if not rooms_cnt.empty:
                rc1, rc2 = st.columns([1, 2])
                with rc1:
                    fig5 = go.Figure(go.Pie(
                        labels=[f"{int(r) if r else '?'} pok." for r in rooms_cnt.index],
                        values=rooms_cnt.values, hole=0.45,
                        marker_colors=[colors_rooms.get(int(r) if r else 0, CLR_MUTED) for r in rooms_cnt.index]))
                    fig5.update_layout(showlegend=True, margin=dict(l=0, r=0, t=20, b=0))
                    apply_plot_theme(fig5)
                    st.plotly_chart(fig5, use_container_width=True)
                with rc2:
                    fig6 = go.Figure()
                    for r, grp in active_u.groupby("rooms"):
                        fig6.add_trace(go.Box(
                            y=grp["price_per_m2"].dropna(), name=f"{int(r) if r else '?'} pok.",
                            marker_color=colors_rooms.get(int(r) if r else 0, CLR_MUTED), boxmean=True))
                    fig6.update_layout(yaxis_title="PLN/m²", showlegend=False)
                    apply_plot_theme(fig6)
                    st.plotly_chart(fig6, use_container_width=True)

    divider()

    # ── Tabela jednostek z watchlist ──────────────
    section_header("Lista jednostek", "Zaznacz ⭐ aby dodać do obserwowanych")
    if units_df is not None and not units_df.empty:
        watched_pp = get_watchlist_ids()
        listing_table(
            units_df, key=f"pp_{pid}",
            watched_ids=watched_pp,
            show_cols=["⭐ Obserwuj", "offer_id", "title", "url", "area_m2",
                       "rooms", "floor", "price_total", "price_per_m2", "Δ cena", "is_active"],
        )
    else:
        st.info("Brak danych jednostkowych dla tego projektu.")

    st.stop()

# ──────────────────────────────────────────────
# NORMALNY WIDOK
# ──────────────────────────────────────────────
page_header("Residential", "Rynek mieszkaniowy Mokotów", color=CLR_RESI)

@st.cache_data(ttl=300)
def load_data():
    summary  = get_residential_summary()
    trend    = get_residential_trend(90)
    zones    = get_residential_zone_summary()
    _resi_hist, _resi_fcast = get_residential_forecast(60)
    forecast = _build_forecast_df(_resi_hist, _resi_fcast)
    devs     = get_developers_table()
    projs    = get_developer_projects()
    health   = compute_residential_health_score()
    kpis     = get_residential_kpis_with_deltas()
    return summary, trend, zones, forecast, devs, projs, health, kpis

try:
    summary, trend, zones, forecast, devs, projs, health, kpis = load_data()
    data_ok = True
except Exception as e:
    st.error(f"Błąd ładowania danych: {e}")
    data_ok = False
    summary = trend = zones = forecast = devs = projs = health = kpis = None

tabs = st.tabs(["Market", "Listings", "Developers", "Projects", "Map", "Forecast", "Delisted"])

# ── TAB 0: MARKET ─────────────────────────────
with tabs[0]:
    if not data_ok:
        st.info("Brak danych — uruchom scraper_residential.py")
    else:
        col_h, col_k = st.columns([1, 3])
        with col_h:
            section_header("Market Health Score")
            health_score_widget(health, CLR_RESI)
        with col_k:
            section_header("Kluczowe wskaźniki")
            kpi_order = ["median_price_m2", "active_listings", "new_listings_7d",
                         "absorbed_30d", "price_reduction_pct"]
            cols = st.columns(len(kpi_order))
            for i, key in enumerate(kpi_order):
                d = kpis.get(key, {})
                with cols[i]:
                    kpi_card(
                        label   = key.replace("_", " ").title(),
                        value   = d.get("value"),
                        unit    = d.get("unit", ""),
                        delta   = d.get("delta"),
                        inverse = d.get("inverse", False),
                    )

        divider()
        section_header("Trend cen sprzedaży", "Avg PLN/m² — ostatnie 90 dni")
        if trend is not None and not trend.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=trend["scrape_date"], y=trend["avg_price_m2"],
                mode="lines+markers", name="Avg PLN/m²",
                line=dict(color=CLR_RESI, width=2), marker=dict(size=4),
            ))
            apply_plot_theme(fig)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Za mało danych trendowych.")

        # ── Transaction Context (Phase 7) ──────────
        divider()
        section_header("Kontekst transakcyjny",
                       "Ceny ofertowe vs rzeczywiste transakcje — bez przechodzenia do innego modułu")
        try:
            pk = get_pricing_kpis("residential", window_days=90)
            tk = get_transaction_kpis("residential", window_days=90)
            liq = compute_liquidity_score("residential")
        except Exception:
            pk, tk, liq = {}, {}, {}

        tc = st.columns(5)
        with tc[0]:
            kpi_card("Median Asking", pk.get("median_asking"), unit="PLN/m² (oferty)")
        with tc[1]:
            kpi_card("Median Transaction", pk.get("median_transaction") or tk.get("median_price_per_m2"),
                     unit="PLN/m² (transakcje)")
        with tc[2]:
            sp = pk.get("spread_pct")
            kpi_card("Spread", f"{sp:+.1f}" if sp is not None else None, unit="%")
        with tc[3]:
            ni = pk.get("negotiation_index")
            kpi_card("Negotiation Index", f"{ni:+.1f}" if ni is not None else None, unit="%")
        with tc[4]:
            kpi_card("Liquidity Score", liq.get("score"),
                     unit=f"/100 {liq.get('label','')}" if liq.get("score") is not None else "n/d")

        nbp = pk.get("nbp_benchmark") if pk else None
        if (pk.get("spread_pct") is None) and nbp:
            st.caption(f"⚠️ Brak wystarczających danych transakcyjnych na poziomie dzielnic — "
                       f"benchmark NBP (Warszawa): transakcje {nbp['transaction']:.0f} vs asking "
                       f"{nbp['asking']:.0f} PLN/m² ({nbp['spread_pct']:+.1f}%). "
                       f"Pełna analiza w module Pricing Intelligence.")
        else:
            st.caption("Pełna analiza spreadu per dzielnica i historia w module Pricing Intelligence.")

# ── TAB 1: LISTINGS ───────────────────────────
with tabs[1]:
    section_header("Wszystkie oferty mieszkaniowe", "Sprzedaż — kliknij link aby otworzyć na Otodom")

    @st.cache_data(ttl=120)
    def load_resi_listings():
        from database import get_conn as _gc
        import pandas as _pd
        with _gc() as conn:
            return _pd.read_sql_query("""
                SELECT offer_id, title, url, subdistrict, area_m2, rooms,
                       price_total, price_per_m2, advertiser_type,
                       first_seen, is_active
                FROM listings
                WHERE asset_class = 'residential'
                  AND transaction_type = 'sale'
                  AND is_active = 1
                ORDER BY price_per_m2 DESC
            """, conn)

    resi_listings = load_resi_listings()
    watched_resi   = get_watchlist_ids()

    if resi_listings.empty:
        st.info("Brak ofert — uruchom scraper_residential.py")
    else:
        fc1, fc2, fc3 = st.columns([1, 1, 2])
        with fc1:
            subs_r = ["Wszystkie"] + sorted(resi_listings["subdistrict"].dropna().unique().tolist())
            sub_r = st.selectbox("Dzielnica", subs_r, key="res_sub_f")
        with fc2:
            rooms_opts = ["Wszystkie"] + sorted(resi_listings["rooms"].dropna().astype(int).unique().tolist())
            rooms_f = st.selectbox("Liczba pokoi", rooms_opts, key="res_rooms_f")
        with fc3:
            p_min = int(resi_listings["price_per_m2"].min() or 0)
            p_max = int(resi_listings["price_per_m2"].max() or 99999)
            price_r = st.slider("PLN/m²", p_min, p_max, (p_min, p_max), key="res_price_f")

        fil_r = resi_listings.copy()
        if sub_r != "Wszystkie":
            fil_r = fil_r[fil_r["subdistrict"] == sub_r]
        if rooms_f != "Wszystkie":
            fil_r = fil_r[fil_r["rooms"] == int(rooms_f)]
        fil_r = fil_r[(fil_r["price_per_m2"] >= price_r[0]) & (fil_r["price_per_m2"] <= price_r[1])]

        st.caption(f"Wyświetlono {len(fil_r)} z {len(resi_listings)} ofert")
        listing_table(
            fil_r, key="resi_listings",
            watched_ids=watched_resi,
            show_cols=["⭐ Obserwuj", "offer_id", "title", "url", "subdistrict",
                       "area_m2", "rooms", "price_total", "price_per_m2",
                       "Δ cena", "advertiser_type", "first_seen"],
        )

# ── TAB 2: DEVELOPERS ─────────────────────────
with tabs[2]:

    @st.cache_data(ttl=300)
    def load_all_investments():
        from database import get_conn as _gc
        import pandas as _pd
        with _gc() as conn:
            df = _pd.read_sql_query("""
                SELECT
                    dp.project_id,
                    dp.name                              AS projekt,
                    COALESCE(dp.developer, '—')          AS deweloper,
                    dp.subdistrict                       AS lokalizacja,
                    dp.address                           AS adres,
                    ps.units_available                   AS dostepne,
                    ROUND(ps.median_price_m2, 0)         AS median_m2,
                    ROUND(ps.min_price / 1000, 0)        AS min_k,
                    ROUND(ps.max_price / 1000, 0)        AS max_k,
                    dp.first_seen                        AS pierwsze_widzenie
                FROM developer_projects dp
                LEFT JOIN project_snapshots ps
                    ON ps.project_id = dp.project_id
                    AND ps.scrape_date = (
                        SELECT MAX(s2.scrape_date) FROM project_snapshots s2
                        WHERE s2.project_id = dp.project_id
                    )
                WHERE dp.is_active = 1
                ORDER BY ps.units_available DESC NULLS LAST, dp.name
            """, conn)
        return df

    inv = load_all_investments()

    if inv is None or inv.empty:
        st.info("Brak danych — uruchom scraper_developer.py")
    else:
        # ── KPI summary ──────────────────────────────────────────────────
        n_proj  = len(inv)
        n_units = int(inv["dostepne"].fillna(0).sum())
        avg_p   = inv["median_m2"].dropna().mean()
        n_devs  = inv[inv["deweloper"] != "—"]["deweloper"].nunique()

        kc = st.columns(4)
        with kc[0]: kpi_card("Inwestycji",         n_proj,               unit="projektów")
        with kc[1]: kpi_card("Dostępnych jedn.",   n_units,              unit="mieszkań/lokali")
        with kc[2]: kpi_card("Median cena/m²",     round(avg_p) if avg_p else None, unit="PLN/m²")
        with kc[3]: kpi_card("Deweloperzy",         n_devs,               unit="firm (zidentyf.)")

        divider()
        section_header("Wszystkie inwestycje deweloperskie na Mokotowie")

        # Filtry
        fc1, fc2 = st.columns([1, 3])
        with fc1:
            locs = ["Wszystkie"] + sorted(inv["lokalizacja"].dropna().unique().tolist())
            loc_filter = st.selectbox("Lokalizacja", locs, key="inv_loc")
        with fc2:
            search = st.text_input("Szukaj (nazwa / deweloper)", key="inv_search", placeholder="np. Evergreen, Murapol…")

        filtered = inv.copy()
        if loc_filter != "Wszystkie":
            filtered = filtered[filtered["lokalizacja"] == loc_filter]
        if search:
            mask = (
                filtered["projekt"].str.lower().str.contains(search.lower(), na=False) |
                filtered["deweloper"].str.lower().str.contains(search.lower(), na=False)
            )
            filtered = filtered[mask]

        display = filtered[[
            "projekt", "deweloper", "lokalizacja", "adres",
            "dostepne", "median_m2", "min_k", "max_k",
        ]].rename(columns={
            "projekt":    "Projekt",
            "deweloper":  "Deweloper",
            "lokalizacja":"Lokalizacja",
            "adres":      "Adres",
            "dostepne":   "Dostępne jedn.",
            "median_m2":  "Median PLN/m²",
            "min_k":      "Min cena (tys. PLN)",
            "max_k":      "Max cena (tys. PLN)",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

        divider()
        section_header("Rozkład cen median wg projektu — top 20")
        top20 = filtered.dropna(subset=["median_m2"]).nlargest(20, "median_m2")
        if not top20.empty:
            fig = go.Figure(go.Bar(
                x=top20["median_m2"],
                y=top20["projekt"].str[:45],
                orientation="h",
                marker_color=CLR_RESI,
                text=top20["median_m2"].apply(lambda x: f"{x:,.0f}"),
                textposition="outside",
            ))
            fig.update_layout(
                height=max(350, len(top20) * 32),
                yaxis=dict(autorange="reversed"),
                xaxis_title="Median PLN/m²",
            )
            apply_plot_theme(fig)
            st.plotly_chart(fig, use_container_width=True)

        divider()
        st.caption("Aby zobaczyć szczegóły projektu (historia + lista jednostek), przejdź do zakładki **Projects** i wpisz ID.")
        pid_q = filtered[["projekt", "project_id"]].rename(columns={"projekt": "Projekt", "project_id": "ID"})
        with st.expander("Pokaż ID projektów"):
            st.dataframe(pid_q, use_container_width=True, hide_index=True)

# ── TAB 3: PROJECTS ───────────────────────────
with tabs[3]:
    section_header("Projekty deweloperskie", "Inwestycje w sprzedaży na Mokotowie")

    @st.cache_data(ttl=300)
    def load_projects_enriched():
        from database import get_conn as _gc
        import pandas as _pd
        with _gc() as conn:
            df = _pd.read_sql_query("""
                SELECT
                    dp.project_id,
                    dp.name,
                    COALESCE(dp.developer, '—') as developer,
                    dp.subdistrict,
                    dp.address,
                    ps.units_available,
                    ROUND(ps.median_price_m2, 0) as median_price_m2,
                    ROUND(ps.min_price / 1000, 0) as min_price_k,
                    ROUND(ps.max_price / 1000, 0) as max_price_k,
                    ps.scrape_date as data_snapshot
                FROM developer_projects dp
                LEFT JOIN project_snapshots ps
                    ON ps.project_id = dp.project_id
                    AND ps.scrape_date = (
                        SELECT MAX(ps2.scrape_date) FROM project_snapshots ps2
                        WHERE ps2.project_id = dp.project_id
                    )
                WHERE dp.is_active = 1
                ORDER BY ps.units_available DESC NULLS LAST
            """, conn)
        return df

    proj_rich = load_projects_enriched()

    if proj_rich is None or proj_rich.empty:
        st.info("Brak danych projektów — uruchom scraper_developer.py")
    else:
        # ── KPI summary ──────────────────────────────────────────────────
        total_proj = len(proj_rich)
        total_units = int(proj_rich["units_available"].fillna(0).sum())
        avg_price = proj_rich["median_price_m2"].dropna().mean()
        unique_devs = proj_rich[proj_rich["developer"] != "—"]["developer"].nunique()

        kc = st.columns(4)
        with kc[0]: kpi_card("Aktywne projekty",   total_proj,            unit="inwestycji")
        with kc[1]: kpi_card("Dostępne jednostki", total_units,           unit="mieszkań")
        with kc[2]: kpi_card("Median cena/m²",     round(avg_price) if avg_price else None, unit="PLN/m²")
        with kc[3]: kpi_card("Deweloperzy",         unique_devs,           unit="firm")

        divider()

        # ── Tabela projektów ─────────────────────────────────────────────
        show = proj_rich[[
            "name", "developer", "subdistrict", "address",
            "units_available", "median_price_m2", "min_price_k", "max_price_k",
        ]].rename(columns={
            "name":           "Projekt",
            "developer":      "Deweloper",
            "subdistrict":    "Lokalizacja",
            "address":        "Adres",
            "units_available":"Dostępne jedn.",
            "median_price_m2":"Median PLN/m²",
            "min_price_k":    "Min cena (tys.)",
            "max_price_k":    "Max cena (tys.)",
        })
        st.dataframe(show, use_container_width=True, hide_index=True)

        divider()

        # ── Wykres: dostępne jednostki per projekt (top 15) ──────────────
        top = proj_rich.dropna(subset=["units_available"]).nlargest(15, "units_available")
        if not top.empty:
            section_header("Dostępne jednostki — top 15 projektów")
            fig = go.Figure(go.Bar(
                x=top["units_available"],
                y=top["name"].str[:40],
                orientation="h",
                marker_color=CLR_RESI,
                text=top["units_available"].astype(int),
                textposition="outside",
            ))
            fig.update_layout(height=max(300, len(top) * 30), yaxis=dict(autorange="reversed"))
            apply_plot_theme(fig)
            st.plotly_chart(fig, use_container_width=True)

        divider()
        st.caption("Aby zobaczyć Project Profile (historia + jednostki), wpisz ID projektu:")
        pid_input = st.text_input("ID projektu", key="pid_input",
                                   placeholder="proj_4BCVV")
        if pid_input:
            st.query_params["project_id"] = pid_input
            st.rerun()

# ── TAB 4: MAP ────────────────────────────────
with tabs[4]:
    section_header("Mapa rynku", "Oferty sprzedaży według dzielnicy")
    if zones is None or zones.empty:
        st.info("Brak danych strefowych.")
    else:
        st.dataframe(
            zones.rename(columns={
                "subdistrict":  "Dzielnica",
                "active_count": "Aktywne oferty",
                "avg_price_m2": "Avg PLN/m²",
                "median_price_m2": "Median PLN/m²",
            }),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("Mapa interaktywna w kolejnym etapie po zebraniu danych geolokalizacji.")

# ── TAB 5: FORECAST ───────────────────────────
with tabs[5]:
    section_header("Prognoza cen", "Trend liniowy + 95% CI — 60 dni")
    if forecast is None or forecast.empty:
        st.info("Za mało danych do prognozy (wymagane min. 7 snapshotów).")
    else:
        fig = go.Figure()
        hist_m = forecast["type"] == "historical"
        fore_m = forecast["type"] == "forecast"

        fig.add_trace(go.Scatter(
            x=forecast.loc[hist_m, "date"],
            y=forecast.loc[hist_m, "value"],
            name="Historyczne", mode="lines+markers",
            line=dict(color=CLR_RESI, width=2),
        ))
        fig.add_trace(go.Scatter(
            x=forecast.loc[fore_m, "date"],
            y=forecast.loc[fore_m, "value"],
            name="Prognoza", mode="lines",
            line=dict(color=CLR_GOLD, width=2, dash="dash"),
        ))
        if "upper" in forecast.columns and "lower" in forecast.columns:
            fore_df = forecast.loc[fore_m]
            fig.add_trace(go.Scatter(
                x=pd.concat([fore_df["date"], fore_df["date"].iloc[::-1]]),
                y=pd.concat([fore_df["upper"], fore_df["lower"].iloc[::-1]]),
                fill="toself", fillcolor="rgba(80,168,112,0.12)",
                line=dict(color="rgba(0,0,0,0)"), name="95% CI",
            ))
        apply_plot_theme(fig)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Model: regresja liniowa. Nie stanowi porady inwestycyjnej.")

# ── TAB 6: DELISTED ───────────────────────────
with tabs[6]:
    from analytics import get_delisting_kpis, get_delisting_trend
    section_header("Delisted Listings", "oferty które zniknęły z rynku — to też market intelligence")
    dk = get_delisting_kpis("residential")
    dc = st.columns(4)
    with dc[0]: kpi_card("Delisted 7d", dk["d7"], "ofert")
    with dc[1]: kpi_card("Delisted 30d", dk["d30"], "ofert", delta=dk["velocity_delta_pct"], inverse=True)
    with dc[2]: kpi_card("Delisted 90d", dk["d90"], "ofert")
    with dc[3]: kpi_card("Tempo", dk["velocity_per_day_30"], "ofert/dzień")

    divider()
    section_header("Trend delistingu", "miesięcznie, ostatnie 180 dni")
    tr = get_delisting_trend("residential", bucket="monthly", days=180)
    if tr.empty:
        st.caption("Brak danych delistingu.")
    else:
        fig = go.Figure(go.Bar(x=tr["period"], y=tr["delisted"], marker_color=CLR_ALERT))
        fig.update_layout(height=300, yaxis_title="delisted")
        apply_plot_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

    divider()
    section_header("Tabela delisted", "ostatnia znana cena + DOM w momencie zniknięcia")
    from database import get_conn as _gc
    with _gc() as _conn:
        deli = pd.read_sql_query("""
            SELECT title, subdistrict, building_name,
                   last_known_price, last_known_price_per_m2,
                   dom_days(COALESCE(published_date, first_seen), delisted_date) AS dom,
                   delisted_date
            FROM listings
            WHERE asset_class='residential' AND transaction_type IN ('sale','invest_unit')
              AND is_active=0 AND delisted_date IS NOT NULL
            ORDER BY delisted_date DESC LIMIT 200
        """, _conn)
    if deli.empty:
        st.caption("Brak delisted ofert.")
    else:
        d = deli.copy()
        d["Cena (PLN)"] = d["last_known_price"].apply(lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else "—")
        d["PLN/m²"] = d["last_known_price_per_m2"].round(0)
        d["DOM (dni)"] = d["dom"]
        d["Oferta"] = d["title"].fillna("—").str.slice(0, 45)
        d = d[["Oferta", "subdistrict", "Cena (PLN)", "PLN/m²", "DOM (dni)", "delisted_date"]]
        d.columns = ["Oferta", "Dzielnica", "Ostatnia cena", "PLN/m²", "DOM (dni)", "Delisted"]
        st.dataframe(d, use_container_width=True, hide_index=True, height=400)
