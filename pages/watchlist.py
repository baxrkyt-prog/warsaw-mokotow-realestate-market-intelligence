"""
pages/watchlist.py — Lista obserwowanych ofert
"""

import streamlit as st
import plotly.graph_objects as go

from analytics import get_watchlist_listings, get_watchlist_ids, set_watchlist
from _ui import (
    inject_css, page_header, section_header, divider, apply_plot_theme,
    listing_table, CLR_GOLD, CLR_OFFICE, CLR_RESI, CLR_TEXT, CLR_MUTED,
)

st.set_page_config(
    page_title="Watchlist · Ocean Plaza MI",
    page_icon="⭐",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()

if st.button("← Home", key="back_home"):
    st.switch_page("app.py")

page_header("Watchlist", "Obserwowane oferty — Office & Residential", color=CLR_GOLD)

@st.cache_data(ttl=60)
def load():
    return get_watchlist_listings(), get_watchlist_ids()

df, watched = load()

if df.empty:
    st.markdown(f"""
    <div style="text-align:center;padding:60px 0;color:{CLR_MUTED};">
        <div style="font-size:48px;margin-bottom:16px;">⭐</div>
        <div style="font-size:18px;font-weight:600;">Brak obserwowanych ofert</div>
        <div style="font-size:13px;margin-top:8px;">
            Zaznacz checkbox ⭐ w tabelach ofert w modułach Office lub Residential
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── KPI ──────────────────────────────────────
from _ui import kpi_card
import pandas as pd

# Policz ile ofert potaniało / zdrożało
changed = df.dropna(subset=["price_change"])
dropped  = int((changed["price_change"] < -1).sum())
risen    = int((changed["price_change"] >  1).sum())

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: kpi_card("Obserwowanych", len(df), unit="ofert")
with c2: kpi_card("Aktywnych", int(df["is_active"].sum()), unit="w ofercie")
with c3: kpi_card("Biurowych",  int((df["asset_class"] == "office").sum()), unit="office")
with c4: kpi_card("Mieszkaniowych", int((df["asset_class"] == "residential").sum()), unit="residential")
with c5: kpi_card("Potaniało", dropped, unit="ofert ↓", inverse=True)
with c6: kpi_card("Zdrożało",  risen,  unit="ofert ↑", inverse=False)

divider()

# ── Filtry ────────────────────────────────────
f1, f2 = st.columns([1, 1])
with f1:
    ac_filter = st.selectbox("Typ", ["Wszystkie", "Office", "Residential"], key="wl_ac")
with f2:
    active_only = st.checkbox("Tylko aktywne", value=False, key="wl_active")

view = df.copy()
if ac_filter == "Office":
    view = view[view["asset_class"] == "office"]
elif ac_filter == "Residential":
    view = view[view["asset_class"] == "residential"]
if active_only:
    view = view[view["is_active"] == 1]

# ── Tabela z możliwością usunięcia z watchlist ─
section_header(f"Obserwowane oferty ({len(view)})")

# Formatuj kolumnę zmiany ceny z kolorową etykietą
def _fmt_change(row):
    if pd.isna(row.get("price_change")) or pd.isna(row.get("price_at_add")):
        return "—"
    chg = row["price_change"]
    pct = row["price_change_pct"]
    sign = "+" if chg > 0 else ""
    return f"{sign}{chg:,.0f} zł ({sign}{pct:.1f}%)"

view = view.copy()
view["Δ cena od obserwacji"] = view.apply(_fmt_change, axis=1)

show_cols = ["⭐ Obserwuj", "title", "url", "asset_class", "subdistrict",
             "building_name", "area_m2", "rooms",
             "price_at_add", "current_price", "Δ cena od obserwacji",
             "is_active", "added_ts"]
show_cols = [c for c in show_cols if c in view.columns or c == "⭐ Obserwuj"]

listing_table(view, key="wl_table", watched_ids=watched, show_cols=show_cols)

st.caption("Odznacz ⭐ żeby usunąć ofertę z watchlisty. Zmiany są zapisywane natychmiast.")

divider()

# ── Trend cen dla obserwowanych ──────────────
section_header("Trend cen obserwowanych ofert")

@st.cache_data(ttl=300)
def load_price_history(offer_ids: tuple):
    from database import get_conn
    import pandas as _pd
    if not offer_ids:
        return _pd.DataFrame()
    placeholders = ",".join("?" * len(offer_ids))
    with get_conn() as conn:
        return _pd.read_sql_query(f"""
            SELECT s.offer_id, s.scrape_date, s.current_price_m2,
                   l.title, l.asset_class
            FROM snapshots s JOIN listings l ON l.offer_id = s.offer_id
            WHERE s.offer_id IN ({placeholders})
              AND s.current_price_m2 IS NOT NULL
            ORDER BY s.scrape_date
        """, conn, params=list(offer_ids))

hist = load_price_history(tuple(view["offer_id"].tolist()))

if hist.empty:
    st.info("Za mało historii cen dla obserwowanych ofert.")
else:
    fig = go.Figure()
    for oid, grp in hist.groupby("offer_id"):
        label = grp["title"].iloc[0][:40] if "title" in grp.columns else oid
        fig.add_trace(go.Scatter(
            x=grp["scrape_date"], y=grp["current_price_m2"],
            mode="lines+markers", name=label,
            marker=dict(size=5), line=dict(width=1.5),
        ))
    apply_plot_theme(fig)
    fig.update_layout(yaxis_title="PLN/m²", legend=dict(font=dict(size=10)))
    st.plotly_chart(fig, use_container_width=True)
