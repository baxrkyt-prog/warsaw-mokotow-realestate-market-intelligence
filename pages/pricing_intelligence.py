"""
pages/pricing_intelligence.py — Pricing Intelligence (Phase 4, flagowy moduł).

Odpowiada na pytanie: "Czy rynek jest mocniejszy czy słabszy niż sugerują
ceny ofertowe?" — spread asking↔transaction, Negotiation Index,
Liquidity Score, Pricing Pressure Score.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from analytics import (
    get_pricing_kpis, get_spread_table, get_spread_history,
    compute_liquidity_score, compute_pricing_pressure_score,
)
from _ui import (
    inject_css, page_header, kpi_card, section_header, divider,
    apply_plot_theme, HEALTH_COLORS, demo_banner,
    CLR_GOLD, CLR_RESI, CLR_OFFICE, CLR_ALERT, CLR_TEXT, CLR_MUTED, CLR_BORDER, CLR_SURFACE,
)

st.set_page_config(
    page_title="Pricing Intelligence · Ocean Plaza MI",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()

CONF_BADGE = {
    "high":   ("HIGH",   "#50a870"),
    "medium": ("MEDIUM", "#c9a84c"),
    "low":    ("LOW",    "#e0924a"),
    "suppress": ("n/d",  "#7a7f8e"),
}


def conf_badge(level: str) -> str:
    label, color = CONF_BADGE.get(level or "suppress", CONF_BADGE["suppress"])
    return (f'<span style="background:{color}22;color:{color};border:1px solid {color};'
            f'border-radius:4px;padding:1px 8px;font-size:10px;font-weight:600;">{label}</span>')


def score_widget(title: str, data: dict):
    """Mini-widget dla Liquidity / Pressure score."""
    score = data.get("score")
    label = data.get("label", "n/d")
    color = HEALTH_COLORS.get(label, "#7a7f8e")
    conf = data.get("confidence", "suppress")
    score_disp = str(score) if score is not None else "—"
    comps = data.get("components", {})
    comp_html = "".join(
        f'<div style="display:flex;justify-content:space-between;font-size:11px;color:{CLR_MUTED};">'
        f'<span>{k}</span><b style="color:{CLR_TEXT};">{v}</b></div>'
        for k, v in comps.items()
    )
    st.markdown(f"""
    <div style="background:{CLR_SURFACE};border:1px solid {CLR_BORDER};border-radius:8px;padding:16px 20px;">
        <div style="font-size:11px;font-weight:600;color:{CLR_MUTED};text-transform:uppercase;
                    letter-spacing:.08em;">{title} {conf_badge(conf)}</div>
        <div style="display:flex;align-items:baseline;gap:12px;margin:6px 0;">
            <span style="font-size:34px;font-weight:700;color:{color};">{score_disp}</span>
            <span style="font-size:13px;font-weight:600;color:{color};">{label}</span>
        </div>
        {comp_html}
    </div>
    """, unsafe_allow_html=True)


if st.button("← Home", key="back_home"):
    st.switch_page("app.py")

page_header(
    "Pricing Intelligence",
    "Spread między rynkiem ofertowym a transakcyjnym · Negotiation Index · Liquidity",
    color=CLR_GOLD,
)

demo_banner("spread, Negotiation Index i Liquidity Score")

# ── Filtry ─────────────────────────────────────
col_a, col_b, _sp = st.columns([1.5, 1.5, 4])
with col_a:
    win = st.selectbox("Okno transakcyjne", options=[30, 90, 180, 365], index=1,
                       format_func=lambda d: f"{d} dni")

@st.cache_data(ttl=120)
def _load(win):
    return (
        get_pricing_kpis("residential", window_days=win),
        get_spread_table("residential", win),
        get_spread_history("residential", days=365),
        compute_liquidity_score("residential"),
        compute_pricing_pressure_score("residential"),
    )

kpis, spread_tbl, history, liquidity, pressure = _load(win)

# ── Data lag warning ──────────────────────────
nbp = kpis.get("nbp_benchmark")
st.markdown(f"""
<div style="background:#1a1d26;border:1px solid {CLR_BORDER};border-radius:6px;
            padding:8px 14px;margin-bottom:18px;font-size:12px;color:{CLR_MUTED};">
⏱️ Dane transakcyjne mają naturalne opóźnienie 1–6 miesięcy względem ofertowych
(rejestracja aktów + publikacja). Spread porównuje <b>dzisiejsze</b> ceny ofertowe
z transakcjami z wybranego okna.
</div>
""", unsafe_allow_html=True)

# ── KPI Row ────────────────────────────────────
section_header("Kluczowe wskaźniki", f"residential · Mokotów · okno {win} dni")

if kpis["median_asking"] is None and nbp is None:
    st.info("Brak zmaterializowanych spreadów. Uruchom: "
            "`python -c \"from analytics import materialize_pricing_spreads; materialize_pricing_spreads()\"`")
else:
    c1, c2, c3, c4 = st.columns(4, gap="small")
    with c1:
        kpi_card("Mediana asking", kpis["median_asking"], "PLN/m² (oferty)")
    with c2:
        kpi_card("Mediana transaction", kpis["median_transaction"], "PLN/m² (transakcje)")
    with c3:
        sp = kpis["spread_pct"]
        kpi_card("Spread", sp, "% (tx − ask)/ask", delta=None)
    with c4:
        ni = kpis["negotiation_index"]
        kpi_card("Negotiation Index", ni, "% pole negocjacji")
    st.markdown(
        f'<div style="text-align:right;margin-top:4px;">Ufność danych: {conf_badge(kpis["confidence"])} '
        f'· {kpis["n_districts"]} dzielnic z danymi</div>',
        unsafe_allow_html=True,
    )

divider()

# ── Score widgets ──────────────────────────────
sc1, sc2 = st.columns(2, gap="large")
with sc1:
    score_widget("Liquidity Score", liquidity)
with sc2:
    score_widget("Pricing Pressure Score", pressure)

divider()

# ── NBP city benchmark ────────────────────────
if nbp:
    section_header("Benchmark NBP (Warszawa, kwartalny)",
                   "ceny transakcyjne BaRN — poziom miasta, rynek wtórny")
    b1, b2, b3 = st.columns(3, gap="small")
    with b1:
        kpi_card("Asking Mokotów", nbp["asking"], "PLN/m² (nasze oferty)")
    with b2:
        kpi_card("Transaction Warszawa", nbp["transaction"], "PLN/m² (NBP)")
    with b3:
        kpi_card("Spread vs miasto", nbp["spread_pct"], "%")
    st.caption("⚠️ Benchmark city-level: porównuje oferty z Mokotowa (dzielnica premium) "
               "ze średnią transakcyjną CAŁEJ Warszawy — ujemny spread jest tu oczekiwany. "
               "Służy do śledzenia TRENDU luki, nie wartości absolutnej.")

divider()

# ── Spread table ───────────────────────────────
section_header("Spread per dzielnica", f"okno {win} dni · sortowane od największego spreadu")
if spread_tbl.empty:
    st.caption("Brak danych district-level w tym oknie (za mało transakcji — suppress).")
else:
    disp = spread_tbl.copy()
    disp["Asking PLN/m²"] = disp["asking_price_per_m2"].round(0)
    disp["Transaction PLN/m²"] = disp["transaction_price_per_m2"].round(0)
    disp["Spread %"] = disp["spread_pct"].round(2)
    disp["Negotiation Index %"] = disp["negotiation_index"].round(2)
    disp = disp.rename(columns={
        "display_name": "Dzielnica", "n_listings": "Oferty",
        "n_transactions": "Transakcje", "confidence": "Ufność",
    })[["Dzielnica", "Asking PLN/m²", "Transaction PLN/m²", "Spread %",
        "Negotiation Index %", "Oferty", "Transakcje", "Ufność"]]
    st.dataframe(disp, use_container_width=True, hide_index=True)

divider()

# ── Historical Spread Analysis ────────────────
section_header("Historical Spread Analysis", "trend spreadu w czasie · per okno transakcyjne")
if history.empty or history["snapshot_date"].nunique() < 2:
    st.caption("Historia spreadu buduje się z codziennych materializacji — wykres pojawi się "
               "po kilku dniach działania crona.")
else:
    fig = go.Figure()
    colors = {30: CLR_ALERT, 90: CLR_GOLD, 180: CLR_OFFICE, 365: CLR_RESI}
    for w in sorted(history["window_days"].unique()):
        sub = history[history["window_days"] == w]
        fig.add_trace(go.Scatter(
            x=sub["snapshot_date"], y=sub["spread_pct"],
            mode="lines+markers", name=f"{w}d",
            line=dict(color=colors.get(w, CLR_MUTED), width=2),
        ))
    fig.add_hline(y=0, line_dash="dot", line_color=CLR_MUTED)
    fig.update_layout(height=380, hovermode="x unified",
                      yaxis_title="Spread % (tx − ask)/ask")
    st.plotly_chart(apply_plot_theme(fig), use_container_width=True)
