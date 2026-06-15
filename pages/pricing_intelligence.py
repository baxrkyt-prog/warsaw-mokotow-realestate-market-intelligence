"""
pages/pricing_intelligence.py — Market Liquidity & Pricing.

Zastępuje stary panel "Ceny Transakcyjne" (oparty na demo/RCN).
Cała logika bazuje WYŁĄCZNIE na danych OFERTOWYCH. Ceny transakcyjne są
ESTYMOWANE z ofertowych przez parametryzowany Discount Factor (zero demo).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from analytics import (
    get_market_kpis, get_market_overview, get_market_liquidity,
    get_delisted_by_district, estimate_transaction_price,
    get_segmentation, get_price_dynamics, DEFAULT_DISCOUNT_FACTOR,
)
from _ui import (
    inject_css, page_header, kpi_card, section_header, divider,
    apply_plot_theme, tracking_maturity_note,
    CLR_GOLD, CLR_RESI, CLR_OFFICE, CLR_ALERT, CLR_POSITIVE,
    CLR_TEXT, CLR_MUTED, CLR_BORDER, CLR_SURFACE,
)

st.set_page_config(page_title="Market Liquidity & Pricing · Ocean Plaza MI",
                   page_icon="📊", layout="wide", initial_sidebar_state="collapsed")
inject_css()

if st.button("← Home", key="back_home"):
    st.switch_page("app.py")

page_header("Market Liquidity & Pricing",
            "Płynność rynku, aktywność i estymacja cen transakcyjnych — z danych ofertowych",
            color=CLR_GOLD)

st.caption("ℹ️ Ceny transakcyjne są **estymowane** z cen ofertowych (Asking × Discount Factor) — "
           "platforma nie korzysta z płatnych/demonstracyjnych danych transakcyjnych. "
           "Współczynnik kalibrowalny poniżej.")
tracking_maturity_note()

# ── Sterowanie ─────────────────────────────────
fc1, fc2, _sp = st.columns([1.4, 1.6, 4])
with fc1:
    seg_label = {"all": "Cały rynek", "residential": "Mieszkania", "office": "Biura",
                 "retail": "Retail", "warehouse": "Magazyny"}
    segment = st.selectbox("Segment", options=list(seg_label.keys()),
                           index=1, format_func=lambda s: seg_label[s])
with fc2:
    discount = st.slider("Discount Factor (estymacja transakcyjnej)",
                         min_value=0.80, max_value=1.00, value=DEFAULT_DISCOUNT_FACTOR,
                         step=0.01, format="%.2f")

kpis = get_market_kpis(segment, discount)
ov = get_market_overview(segment)

# ── SEKCJA 8 — KPI TOP ─────────────────────────
section_header("Kluczowe wskaźniki rynku")
k = st.columns(7, gap="small")
with k[0]: kpi_card("Active Listings", kpis["active"], "ofert")
with k[1]: kpi_card("New 30D", kpis["new_30"], "ofert")
with k[2]: kpi_card("Delisted 30D", kpis["delisted_30"], "ofert")
with k[3]: kpi_card("Absorption", kpis["absorption_rate"], "%")
with k[4]: kpi_card("Median /m²", kpis["median_price_m2"], "PLN")
with k[5]: kpi_card("Est. Transaction /m²", kpis["est_transaction_m2"], "PLN")
with k[6]: kpi_card("Median Age", kpis["median_listing_age"], "dni")

divider()

# ── SEKCJA 1 — MARKET OVERVIEW ─────────────────
section_header("Market Overview", f"segment: {seg_label[segment]}")
o = st.columns(5, gap="small")
with o[0]: kpi_card("Aktywne", ov["active"], "ofert")
with o[1]: kpi_card("Nowe 7d", ov["new_7"], "ofert")
with o[2]: kpi_card("Nowe 30d", ov["new_30"], "ofert")
with o[3]: kpi_card("Usunięte 7d", ov["delisted_7"], "ofert")
with o[4]: kpi_card("Usunięte 30d", ov["delisted_30"], "ofert")
o2 = st.columns(4, gap="small")
with o2[0]: kpi_card("Średnia cena", ov["avg_price"], "PLN")
with o2[1]: kpi_card("Mediana ceny", ov["median_price"], "PLN")
with o2[2]: kpi_card("Średnia /m²", ov["avg_price_m2"], "PLN/m²")
with o2[3]: kpi_card("Mediana /m²", ov["median_price_m2"], "PLN/m²")
if segment == "all":
    st.caption("⚠️ Dla całego rynku ceny mieszają sprzedaż i najem (PLN/m² vs PLN/m²/mc) — "
               "do analizy cen wybierz konkretny segment.")

divider()

# ── SEKCJA 2 + 4 — LIQUIDITY + ESTIMATED PRICE ─
cL, cR = st.columns(2, gap="large")
with cL:
    section_header("Market Liquidity", "absorpcja i czas ekspozycji")
    liq = get_market_liquidity(segment, 30)
    lc = st.columns(2)
    with lc[0]: kpi_card("Absorption Rate", liq["absorption_rate"], "% (del/new 30d)")
    with lc[1]: kpi_card("Median ekspozycji", liq["median_exposure"], "dni")
    lc2 = st.columns(2)
    with lc2[0]: kpi_card("Śr. ekspozycja", liq["avg_exposure"], "dni")
    with lc2[1]: kpi_card("Nowe / Usunięte", f"{liq['new_w']} / {liq['delisted_w']}", "30d")
    older = liq["older_than"]
    if older:
        st.markdown(f'<div style="font-size:12px;color:{CLR_MUTED};margin-top:6px;">Oferty starsze niż:</div>',
                    unsafe_allow_html=True)
        ob = st.columns(4)
        for i, t in enumerate(("30d", "60d", "90d", "180d")):
            with ob[i]: kpi_card(f">{t}", older.get(t, 0), "ofert")

with cR:
    section_header("Estimated Transaction Price", f"Asking × {discount:.2f}")
    est = estimate_transaction_price(segment, discount)
    ec = st.columns(2)
    with ec[0]: kpi_card("Median Asking /m²", est["median_asking_m2"], "PLN/m²")
    with ec[1]: kpi_card("Est. Transaction /m²", est["est_transaction_m2"], "PLN/m²")
    ec2 = st.columns(2)
    with ec2[0]: kpi_card("Median Asking", est["median_asking"], "PLN")
    with ec2[1]: kpi_card("Est. Transaction", est["est_transaction"], "PLN")
    st.markdown(f"""
    <div style="background:{CLR_SURFACE};border-left:3px solid {CLR_GOLD};border-radius:6px;
                padding:12px 16px;margin-top:10px;font-size:12px;color:{CLR_TEXT};">
        Implikowane pole negocjacji: <b>{est['implied_negotiation_pct']:.0f}%</b>.
        Discount Factor parametryzowany — docelowo kalibrowany na realnych transakcjach
        (gdy pojawi się dostęp do RCN bez kosztów).
    </div>""", unsafe_allow_html=True)

divider()

# ── SEKCJA 3 — DELISTED PER DZIELNICA ──────────
section_header("Delisted Listings per dzielnica", "oferty usunięte z rynku — sygnał absorpcji")
deli = get_delisted_by_district(segment)
if deli.empty:
    st.caption("Brak danych delistingu w tym segmencie.")
else:
    d = deli.rename(columns={"district_label": "Dzielnica", "d7": "Delisted 7d",
                             "d30": "Delisted 30d", "d90": "Delisted 90d", "active": "Aktywne"})
    st.dataframe(d, use_container_width=True, hide_index=True)

divider()

# ── SEKCJA 5 — SEGMENTATION ────────────────────
section_header("Segmentacja", "wg typu nieruchomości i przedziału metrażu")
seg = get_segmentation(discount)
sc1, sc2 = st.columns(2, gap="large")
with sc1:
    st.markdown(f'<div style="font-size:13px;font-weight:600;color:{CLR_TEXT};margin-bottom:4px;">Wg typu</div>', unsafe_allow_html=True)
    bt = seg["by_type"].copy()
    bt["segment"] = bt["segment"].map(seg_label).fillna(bt["segment"])
    bt = bt.rename(columns={"segment": "Segment", "active": "Aktywne",
                            "median_m2": "Mediana /m²", "est_transaction_m2": "Est. tx /m²"})
    st.dataframe(bt, use_container_width=True, hide_index=True)
with sc2:
    st.markdown(f'<div style="font-size:13px;font-weight:600;color:{CLR_TEXT};margin-bottom:4px;">Wg metrażu (mieszkania)</div>', unsafe_allow_html=True)
    ba = seg["by_area"].rename(columns={"bucket": "Metraż m²", "active": "Aktywne",
                                        "median_m2": "Mediana /m²", "est_transaction_m2": "Est. tx /m²"})
    st.dataframe(ba, use_container_width=True, hide_index=True)

divider()

# ── SEKCJA 6 — PRICE DYNAMICS ──────────────────
section_header("Price Dynamics", "zmiana ceny /m² w czasie (z dziennych snapshotów)")
dyn = get_price_dynamics(segment)
has_dyn = any(v["median_chg"] is not None or v["avg_chg"] is not None for v in dyn.values())
if not has_dyn:
    st.caption("Dynamika cen buduje się z dziennych snapshotów — wartości pojawią się gdy "
               "historia obejmie 7/30/90 dni (obecnie zbyt krótka).")
else:
    dc = st.columns(3)
    for i, w in enumerate(("7d", "30d", "90d")):
        with dc[i]:
            mc = dyn[w]["median_chg"]
            ac = dyn[w]["avg_chg"]
            kpi_card(f"Median /m² Δ{w}", f"{mc:+.1f}" if mc is not None else None, "%")
            st.caption(f"Średnia Δ{w}: {ac:+.1f}%" if ac is not None else f"Średnia Δ{w}: n/d")
