"""
pages/transactions.py — Transaction Intelligence (Phase 5, pełne taby).

Trzy taby:
  Overview   — KPI row (median/avg/count/volume/liquidity) + ostatnie transakcje
  Trends     — Price / Count / Volume over time, toggle zakresu 30/90/180/12m
  Geographic — tabela per dzielnica (cena, liczba, wolumen, liquidity) + bar
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from analytics import (
    get_transaction_kpis, get_transaction_trend,
    get_transaction_geography, get_recent_transactions,
    compute_liquidity_score,
)
from _ui import (
    inject_css, page_header, kpi_card, section_header, divider,
    apply_plot_theme, CLR_GOLD, CLR_RESI, CLR_OFFICE, CLR_ALERT,
    CLR_TEXT, CLR_MUTED, CLR_BORDER, CLR_SURFACE,
)

st.set_page_config(
    page_title="Transactions · Ocean Plaza MI",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()

CONF_BADGE = {
    "high":   ("HIGH", "#50a870"), "medium": ("MEDIUM", "#c9a84c"),
    "low":    ("LOW", "#e0924a"),  "suppress": ("n/d", "#7a7f8e"),
}


def conf_badge(level: str) -> str:
    label, color = CONF_BADGE.get(level or "suppress", CONF_BADGE["suppress"])
    return (f'<span style="background:{color}22;color:{color};border:1px solid {color};'
            f'border-radius:4px;padding:1px 8px;font-size:10px;font-weight:600;">{label}</span>')


if st.button("← Home", key="back_home"):
    st.switch_page("app.py")

page_header(
    "Transaction Intelligence",
    "Rzeczywiste ceny transakcyjne — nie ofertowe.",
    color=CLR_GOLD,
)

# ── Globalne filtry ────────────────────────────
col_a, col_b, _sp = st.columns([1.5, 1.5, 4])
with col_a:
    pt = st.selectbox("Typ nieruchomości",
                      options=["(wszystkie)", "residential", "office", "land", "commercial"],
                      index=1)
    property_type = None if pt == "(wszystkie)" else pt
with col_b:
    win = st.selectbox("Okno czasowe", options=[30, 90, 180, 365], index=1,
                       format_func=lambda d: f"{d} dni")


@st.cache_data(ttl=120)
def _kpis(pt, win):
    return get_transaction_kpis(property_type=pt, window_days=win)

@st.cache_data(ttl=120)
def _liquidity(pt):
    return compute_liquidity_score(pt or "residential")

kpis = _kpis(property_type, win)

# Empty state — wspólny dla całej strony
if kpis["transaction_count"] == 0:
    st.info(
        "Brak danych transakcyjnych w wybranym oknie.\n\n"
        "Zaimportuj plik:\n"
        "`python -m collectors run csv_import --file <plik.csv> --mapping <mapping.json>`\n\n"
        "albo wypis RCN:\n"
        "`python -m collectors run rcn --file <wypis.csv>`"
    )
    st.stop()

# Banner DEMO jeśli dane pochodzą z fixture
@st.cache_data(ttl=300)
def _has_demo():
    from database import get_conn
    with get_conn() as c:
        r = c.execute("SELECT COUNT(*) n FROM transactions WHERE source LIKE 'demo%' OR source LIKE 'fixture%'").fetchone()
    return r["n"] > 0

if _has_demo():
    st.caption("ℹ️ Zbiór zawiera dane DEMO (poglądowe). Przed produkcją zaimportuj realny wypis RCN.")

tabs = st.tabs(["Overview", "Trends", "Geographic"])

# ── TAB 0: OVERVIEW ────────────────────────────
with tabs[0]:
    section_header("Kluczowe wskaźniki", f"okno: {win} dni")
    liq = _liquidity(property_type)

    cols = st.columns(5, gap="small")
    with cols[0]:
        kpi_card("Mediana ceny", kpis["median_price_per_m2"], "PLN/m²")
    with cols[1]:
        kpi_card("Średnia ceny", kpis["average_price_per_m2"], "PLN/m²",
                 delta=kpis["deltas"]["average_price_per_m2"])
    with cols[2]:
        kpi_card("Liczba transakcji", kpis["transaction_count"], "szt.",
                 delta=kpis["deltas"]["transaction_count"])
    with cols[3]:
        vol = kpis["transaction_volume"]
        kpi_card("Wolumen", round(vol / 1_000_000, 1) if vol else 0, "mln PLN",
                 delta=kpis["deltas"]["transaction_volume"])
    with cols[4]:
        liq_val = liq.get("score")
        kpi_card("Liquidity Score", liq_val if liq_val is not None else "n/d",
                 f"/100 {liq.get('label','')}" if liq_val is not None else liq.get("reason", ""))

    divider()
    section_header("Ostatnie transakcje", "max 100 rekordów")
    recent = get_recent_transactions(property_type=property_type, limit=100)
    if recent.empty:
        st.caption("Brak transakcji do wyświetlenia.")
    else:
        rdisp = recent.copy()
        rdisp["transaction_price"] = rdisp["transaction_price"].apply(
            lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else "—")
        rdisp["transaction_price_per_m2"] = rdisp["transaction_price_per_m2"].apply(
            lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else "—")
        rdisp.columns = ["Data", "Typ", "Rynek", "Dzielnica", "Adres", "m²", "Pokoje",
                         "Cena (PLN)", "PLN/m²", "Waluta", "Źródło"]
        st.dataframe(rdisp, use_container_width=True, hide_index=True, height=420)

# ── TAB 1: TRENDS ──────────────────────────────
with tabs[1]:
    section_header("Trendy czasowe", "ceny, liczba i wolumen transakcji")
    rng = st.radio("Zakres", options=[30, 90, 180, 365], index=3, horizontal=True,
                   format_func=lambda d: "12 mies." if d == 365 else f"{d} dni",
                   key="trend_range")
    bucket = "daily" if rng <= 30 else ("weekly" if rng <= 90 else "monthly")
    trend = get_transaction_trend(property_type=property_type, days=rng, bucket=bucket)

    if trend.empty or len(trend) < 2:
        st.caption("Za mało danych do narysowania trendów w tym zakresie.")
    else:
        # 1) Transaction Price Over Time
        st.markdown(f'<div style="font-size:13px;font-weight:600;color:{CLR_TEXT};margin:8px 0 4px;">'
                    f'Cena transakcyjna w czasie (PLN/m²)</div>', unsafe_allow_html=True)
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=trend["date_bucket"], y=trend["median_p"],
                                  mode="lines+markers", name="Mediana",
                                  line=dict(color=CLR_GOLD, width=2)))
        fig1.add_trace(go.Scatter(x=trend["date_bucket"], y=trend["mean_p"],
                                  mode="lines", name="Średnia",
                                  line=dict(color=CLR_OFFICE, width=1, dash="dot")))
        fig1.update_layout(height=300, hovermode="x unified", yaxis_title="PLN/m²")
        st.plotly_chart(apply_plot_theme(fig1), use_container_width=True)

        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown(f'<div style="font-size:13px;font-weight:600;color:{CLR_TEXT};margin:8px 0 4px;">'
                        f'Liczba transakcji</div>', unsafe_allow_html=True)
            fig2 = go.Figure(go.Bar(x=trend["date_bucket"], y=trend["cnt"],
                                    marker_color=CLR_OFFICE))
            fig2.update_layout(height=280, yaxis_title="szt.")
            st.plotly_chart(apply_plot_theme(fig2), use_container_width=True)
        with c2:
            st.markdown(f'<div style="font-size:13px;font-weight:600;color:{CLR_TEXT};margin:8px 0 4px;">'
                        f'Wolumen transakcji (mln PLN)</div>', unsafe_allow_html=True)
            vol_m = (trend["volume"] / 1_000_000).round(2)
            fig3 = go.Figure(go.Bar(x=trend["date_bucket"], y=vol_m, marker_color=CLR_RESI))
            fig3.update_layout(height=280, yaxis_title="mln PLN")
            st.plotly_chart(apply_plot_theme(fig3), use_container_width=True)

        st.caption(f"Agregacja: {bucket} · zakres: {rng} dni. "
                   "Mediany liczone z winsoryzacją (odporne na transakcje skrajne).")

# ── TAB 2: GEOGRAPHIC ──────────────────────────
with tabs[2]:
    section_header("Rozkład geograficzny", f"per dzielnica · okno {win} dni")
    geo = get_transaction_geography(property_type=property_type, window_days=win)
    if geo.empty:
        st.caption("Brak danych geograficznych w tym oknie.")
    else:
        # Liquidity per dzielnica
        liq_by_dn = {}
        for dn in geo["district_norm"].dropna().unique():
            if dn == "(unknown)":
                continue
            ls = compute_liquidity_score(property_type or "residential", district_norm=dn)
            liq_by_dn[dn] = ls.get("score")

        gdisp = geo.copy()
        gdisp["Mediana PLN/m²"] = gdisp["median_p"].round(0)
        gdisp["Średnia PLN/m²"] = gdisp["mean_p"].round(0)
        gdisp["Wolumen (mln PLN)"] = (gdisp["volume"] / 1_000_000).round(2)
        gdisp["Liquidity"] = gdisp["district_norm"].map(liq_by_dn).apply(
            lambda v: int(v) if pd.notna(v) else None)
        gdisp = gdisp.rename(columns={"display_name": "Dzielnica", "n": "Transakcje"})
        gdisp = gdisp[["Dzielnica", "Transakcje", "Mediana PLN/m²", "Średnia PLN/m²",
                       "Wolumen (mln PLN)", "Liquidity"]]
        st.dataframe(gdisp, use_container_width=True, hide_index=True)

        divider()
        st.markdown(f'<div style="font-size:13px;font-weight:600;color:{CLR_TEXT};margin:8px 0 4px;">'
                    f'Mediana ceny transakcyjnej wg dzielnicy</div>', unsafe_allow_html=True)
        gsort = geo.sort_values("median_p", ascending=False)
        fig = go.Figure(go.Bar(
            x=gsort["display_name"], y=gsort["median_p"].round(0),
            marker_color=CLR_GOLD, text=gsort["median_p"].round(0), textposition="outside"))
        fig.update_layout(height=340, yaxis_title="PLN/m²", xaxis_title="")
        st.plotly_chart(apply_plot_theme(fig), use_container_width=True)
        st.caption("Dzielnice z <3 transakcjami nie są pokazywane jako wiarygodne mediany.")
