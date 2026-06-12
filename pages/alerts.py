"""
pages/alerts.py — Alert Center
Dwie kolumny: Office Alerts | Residential Alerts
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from analytics import get_alerts, mark_alerts_read, check_and_fire_alerts
from _ui import (
    inject_css, page_header, section_header, divider,
    CLR_ALERT, CLR_OFFICE, CLR_RESI, CLR_MUTED, CLR_SURFACE, CLR_BORDER, CLR_TEXT,
)

st.set_page_config(
    page_title="Alert Center · Ocean Plaza MI",
    page_icon="🔔",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()

if st.button("← Home", key="back_home"):
    st.switch_page("app.py")

page_header("Alert Center", "Sygnały rynkowe i anomalie", color=CLR_ALERT)

# ── Odśwież alerty ────────────────────────────
col_act1, col_act2, col_act3 = st.columns([1, 1, 4])
with col_act1:
    if st.button("🔄 Sprawdź nowe alerty", use_container_width=True):
        try:
            check_and_fire_alerts()
            st.success("Alerty zaktualizowane.")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Błąd: {e}")
with col_act2:
    if st.button("✓ Oznacz wszystkie jako przeczytane", use_container_width=True):
        try:
            mark_alerts_read()
            st.success("Wszystkie alerty przeczytane.")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Błąd: {e}")

divider()

# ── Wczytaj alerty ────────────────────────────
@st.cache_data(ttl=60)
def load_alerts():
    all_al = get_alerts(unread_only=False)
    return all_al

try:
    df = load_alerts()
    has_data = not df.empty
except Exception as e:
    st.error(f"Błąd ładowania alertów: {e}")
    df = pd.DataFrame()
    has_data = False

if not has_data:
    st.info("Brak alertów. Kliknij 'Sprawdź nowe alerty' aby wygenerować pierwsze alerty.")
    st.stop()

# ── Filtry ────────────────────────────────────
filter_col, _, _ = st.columns([1, 1, 2])
with filter_col:
    show_unread = st.checkbox("Tylko nieprzeczytane", value=False)

if show_unread and "is_new" in df.columns:
    df = df[df["is_new"] == 1]

# ── Podział na Office / Residential ──────────
if "asset_class" in df.columns:
    office_df = df[df["asset_class"] == "office"].copy()
    resi_df   = df[df["asset_class"].isin(["residential", "developer"])].copy()
    other_df  = df[~df["asset_class"].isin(["office", "residential", "developer"])].copy()
else:
    office_df = df.copy()
    resi_df   = pd.DataFrame()
    other_df  = pd.DataFrame()

# ── Renderuj alerty ───────────────────────────
def render_alert_row(row):
    is_new = row.get("is_new", 0)
    atype  = row.get("alert_type", "")
    msg    = row.get("message", "")
    ts     = str(row.get("alert_ts", ""))[:16].replace("T", " ")
    val    = row.get("value")
    thr    = row.get("threshold")

    badge = '<span style="background:#e05c5c;color:white;font-size:10px;font-weight:700;padding:1px 6px;border-radius:8px;margin-right:8px;">NEW</span>' if is_new else ""
    val_str = f" | wartość: <b>{val:.1f}</b>" if val is not None else ""
    thr_str = f" | próg: {thr:.1f}" if thr is not None else ""

    bg = "#1e1212" if is_new else CLR_SURFACE
    border = "#e05c5c" if is_new else CLR_BORDER

    st.markdown(f"""
    <div style="background:{bg};border:1px solid {border};border-radius:6px;
                padding:10px 14px;margin-bottom:8px;">
        <div style="font-size:11px;color:{CLR_MUTED};margin-bottom:4px;">
            {badge}{ts} · <span style="color:{CLR_TEXT}">{atype}</span>{val_str}{thr_str}
        </div>
        <div style="font-size:13px;color:{CLR_TEXT};">{msg}</div>
    </div>
    """, unsafe_allow_html=True)


col_off, col_res = st.columns(2, gap="large")

with col_off:
    n_new_off = int((office_df["is_new"] == 1).sum()) if not office_df.empty and "is_new" in office_df.columns else 0
    badge_str = f' <span style="background:#e05c5c;color:white;font-size:10px;padding:1px 6px;border-radius:8px;">{n_new_off}</span>' if n_new_off > 0 else ""
    st.markdown(f'<div style="font-size:15px;font-weight:700;color:{CLR_OFFICE};margin-bottom:16px;">🏢 Office Alerts{badge_str}</div>', unsafe_allow_html=True)

    if office_df.empty:
        st.markdown(f'<div style="color:{CLR_MUTED};font-size:13px;">Brak alertów biurowych.</div>', unsafe_allow_html=True)
    else:
        for _, row in office_df.head(50).iterrows():
            render_alert_row(row)

with col_res:
    n_new_res = int((resi_df["is_new"] == 1).sum()) if not resi_df.empty and "is_new" in resi_df.columns else 0
    badge_str = f' <span style="background:#e05c5c;color:white;font-size:10px;padding:1px 6px;border-radius:8px;">{n_new_res}</span>' if n_new_res > 0 else ""
    st.markdown(f'<div style="font-size:15px;font-weight:700;color:{CLR_RESI};margin-bottom:16px;">🏠 Residential Alerts{badge_str}</div>', unsafe_allow_html=True)

    if resi_df.empty:
        st.markdown(f'<div style="color:{CLR_MUTED};font-size:13px;">Brak alertów mieszkaniowych.</div>', unsafe_allow_html=True)
    else:
        for _, row in resi_df.head(50).iterrows():
            render_alert_row(row)

# ── Inne alerty (bez asset_class) ────────────
if not other_df.empty:
    divider()
    section_header("Inne alerty")
    for _, row in other_df.head(20).iterrows():
        render_alert_row(row)
