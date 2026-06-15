"""
pages/lifecycle.py — Listing Lifecycle Intelligence (Market Flow).

Odpowiada: jak płynny jest rynek, jak szybko znikają oferty, które są stale.
KPI + funnel + New vs Delisted flow + DOM distribution + stale table z flagami.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from analytics import (
    get_lifecycle_kpis, get_lifecycle_funnel, get_listing_flow,
    get_dom_stats, get_delisting_kpis, get_delisting_trend, get_stale_listings,
)
from _ui import (
    inject_css, page_header, kpi_card, section_header, divider,
    apply_plot_theme, lifecycle_flag,
    CLR_GOLD, CLR_RESI, CLR_OFFICE, CLR_ALERT, CLR_POSITIVE,
    CLR_TEXT, CLR_MUTED, CLR_BORDER, CLR_SURFACE,
)

st.set_page_config(page_title="Lifecycle · Ocean Plaza MI", page_icon="🔄",
                   layout="wide", initial_sidebar_state="collapsed")
inject_css()

if st.button("← Home", key="back_home"):
    st.switch_page("app.py")

page_header("Listing Lifecycle Intelligence",
            "Market flow — jak szybko rynek się obraca, co znika, co się starzeje",
            color=CLR_GOLD)

ac = st.radio("Segment", options=["residential", "office"], horizontal=True,
              format_func=lambda x: "Mieszkania" if x == "residential" else "Biura")

k = get_lifecycle_kpis(ac)
dom = get_dom_stats(ac)
funnel = get_lifecycle_funnel(ac)
deli = get_delisting_kpis(ac)

# Ostrzeżenie o dojrzewaniu DOM
if not k["real_dom"]:
    st.caption("⏳ DOM liczony od startu trackingu (realna data publikacji z Otodom dochodzi "
               "przy kolejnych scrape'ach) — wartości będą rosły, aż historia dojrzeje.")

# ── KPI ROW ────────────────────────────────────
section_header("Market Flow — kluczowe wskaźniki")
c = st.columns(5, gap="small")
with c[0]: kpi_card("Nowe (30d)", k["new_30d"], "ofert")
with c[1]: kpi_card("Aktywne", k["active"], "ofert")
with c[2]: kpi_card("Delisted (30d)", k["delisted_30d"], "ofert")
with c[3]: kpi_card("Median DOM", k["median_dom"], "dni")
with c[4]: kpi_card("Turnover (90d)", k["turnover_90d"], "%")

divider()

colL, colR = st.columns([1, 1.3], gap="large")

# ── FUNNEL ─────────────────────────────────────
with colL:
    section_header("Lifecycle Funnel", "NEW → ACTIVE → PRICE CHANGED → DELISTED")
    stages = [("NEW (30d)", funnel["NEW"], CLR_POSITIVE),
              ("ACTIVE", funnel["ACTIVE"], CLR_GOLD),
              ("PRICE CHANGED", funnel["PRICE_CHANGED"], CLR_OFFICE),
              ("DELISTED", funnel["DELISTED"], CLR_MUTED)]
    maxv = max((v for _, v, _ in stages), default=1) or 1
    for label, val, color in stages:
        pct = int(val / maxv * 100)
        st.markdown(f"""
        <div style="margin-bottom:10px;">
            <div style="display:flex;justify-content:space-between;font-size:12px;
                        color:{CLR_TEXT};margin-bottom:3px;">
                <span>{label}</span><b>{val}</b></div>
            <div style="background:{CLR_BORDER};border-radius:4px;height:22px;">
                <div style="background:{color};width:{pct}%;height:22px;border-radius:4px;"></div>
            </div>
        </div>""", unsafe_allow_html=True)

# ── DOM DISTRIBUTION ───────────────────────────
with colR:
    section_header("Rozkład Days on Market", "ile ofert w każdym przedziale wiekowym")
    buckets = dom["buckets"]
    colors = [CLR_POSITIVE, CLR_GOLD, "#e0924a", CLR_ALERT, "#8b2f2f"]
    fig = go.Figure(go.Bar(
        x=list(buckets.keys()), y=list(buckets.values()),
        marker_color=colors, text=list(buckets.values()), textposition="outside"))
    fig.update_layout(height=300, yaxis_title="ofert", xaxis_title="dni na rynku")
    st.plotly_chart(apply_plot_theme(fig), use_container_width=True)

divider()

# ── LISTING FLOW (New vs Delisted) ─────────────
section_header("Listing Flow", "Nowe vs Delisted w czasie — leading indicator kierunku rynku")
flow = get_listing_flow(ac, days=180, bucket="weekly")
if flow.empty or len(flow) < 2:
    st.caption("Za mało historii — wykres flow zbuduje się po kilku tygodniach scrapowania.")
else:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=flow["period"], y=flow["new_listings"],
                         name="Nowe", marker_color=CLR_POSITIVE))
    fig.add_trace(go.Bar(x=flow["period"], y=-flow["delisted"],
                         name="Delisted", marker_color=CLR_ALERT))
    fig.add_trace(go.Scatter(x=flow["period"], y=flow["net_flow"],
                             name="Net flow", line=dict(color=CLR_GOLD, width=2)))
    fig.update_layout(height=340, barmode="relative", hovermode="x unified",
                      yaxis_title="oferty (+nowe / −delisted)")
    st.plotly_chart(apply_plot_theme(fig), use_container_width=True)

divider()

# ── DELISTING + STALE ──────────────────────────
d1, d2 = st.columns([1, 1.6], gap="large")
with d1:
    section_header("Delisting Velocity")
    kpi_card("Delisted 7d", deli["d7"], "ofert")
    kpi_card("Delisted 30d", deli["d30"], "ofert",
             delta=deli["velocity_delta_pct"], inverse=True)
    kpi_card("Tempo", deli["velocity_per_day_30"], "ofert/dzień")

with d2:
    section_header("Stale Listings", "oferty starsze niż 2× mediana DOM — kandydaci do analizy")
    stale = get_stale_listings(ac, limit=100)
    if stale.empty:
        st.caption("Brak ofert spełniających próg „stale" w bieżących danych "
                   "(DOM dojrzewa — wróć gdy historia się nazbiera).")
    else:
        med = dom["median_dom"] or 60
        s = stale.copy()
        s["Flaga"] = s["dom"].apply(lambda d: lifecycle_flag(d, True, med))
        s["Cena PLN/m²"] = s["price_per_m2"].round(0)
        s["DOM (dni)"] = s["dom"]
        s["Zmiany ceny"] = s["price_changes"]
        s["Oferta"] = s["title"].fillna(s["offer_id"]).str.slice(0, 45)
        s = s[["Flaga", "Oferta", "subdistrict", "Cena PLN/m²", "DOM (dni)", "Zmiany ceny"]]
        s.columns = ["Flaga", "Oferta", "Dzielnica", "Cena PLN/m²", "DOM (dni)", "Zmiany ceny"]
        st.dataframe(s, use_container_width=True, hide_index=True, height=360)

st.caption("Legenda: 🟢 New (≤30d) · 🟡 Active · 🟠 Aging (≥median) · 🔴 Stale (≥2×median) · ⚫ Delisted")
