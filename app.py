"""
app.py — Ocean Plaza Market Intelligence · Home Screen
"""

import streamlit as st
from analytics import get_alerts, get_scrape_log, get_last_scrape_ts
from _ui import inject_css, page_header, CLR_GOLD, CLR_OFFICE, CLR_RESI, CLR_ALERT

st.set_page_config(
    page_title="Ocean Plaza · Market Intelligence",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

# ──────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────
col_logo, col_ts = st.columns([3, 1])
with col_logo:
    st.markdown(f"""
    <div style="padding: 24px 0 8px;">
        <div style="font-size:11px;font-weight:600;color:#7a7f8e;letter-spacing:.1em;text-transform:uppercase;">
            Ocean Plaza · ul. Domaniewska 50, Mokotów
        </div>
        <div style="font-size:30px;font-weight:700;color:{CLR_GOLD};margin-top:4px;">
            Market Intelligence
        </div>
    </div>
    """, unsafe_allow_html=True)
with col_ts:
    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
    ts = get_last_scrape_ts()
    st.markdown(f'<div style="font-size:11px;color:#7a7f8e;text-align:right;padding-top:24px;">Ostatnia aktualizacja<br><b style="color:#e8eaf0;">{ts}</b></div>', unsafe_allow_html=True)

st.markdown('<div style="border-bottom: 1px solid #2a2d35; margin-bottom: 32px;"></div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────
# ALERT BANNER
# ──────────────────────────────────────────────
try:
    alerts_df = get_alerts(unread_only=True)
    n_alerts = len(alerts_df)
except Exception:
    n_alerts = 0

if n_alerts > 0:
    st.markdown(f"""
    <div style="background:#2d1a1a;border:1px solid #e05c5c;border-radius:8px;
                padding:12px 20px;margin-bottom:24px;display:flex;align-items:center;gap:12px;">
        <span style="font-size:18px;">🔔</span>
        <span style="color:#e05c5c;font-weight:600;">{n_alerts} nowych alertów rynkowych</span>
        <span style="color:#7a7f8e;font-size:13px;">— przejdź do Alert Center po szczegóły</span>
    </div>
    """, unsafe_allow_html=True)

# ──────────────────────────────────────────────
# MODULE CARDS
# ──────────────────────────────────────────────
st.markdown('<div style="font-size:13px;color:#7a7f8e;margin-bottom:16px;">Wybierz moduł</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4, gap="large")

with c1:
    st.markdown(f"""
    <div class="module-card" style="border-top: 3px solid {CLR_OFFICE};">
        <div class="module-icon">🏢</div>
        <div class="module-title" style="color:{CLR_OFFICE};">Office Market</div>
        <div class="module-sub">Rynek biurowy Mokotów<br>Stawki, absorpcja, konkurencja, pipeline</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    if st.button("Otwórz Office →", key="btn_office", use_container_width=True):
        st.switch_page("pages/office.py")

with c2:
    st.markdown(f"""
    <div class="module-card" style="border-top: 3px solid {CLR_RESI};">
        <div class="module-icon">🏠</div>
        <div class="module-title" style="color:{CLR_RESI};">Residential</div>
        <div class="module-sub">Rynek mieszkaniowy Mokotów<br>Ceny, deweloperzy, projekty, prognoza</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    if st.button("Otwórz Residential →", key="btn_resi", use_container_width=True):
        st.switch_page("pages/residential.py")

with c3:
    alert_badge = f' <span class="alert-badge">{n_alerts}</span>' if n_alerts > 0 else ""
    st.markdown(f"""
    <div class="module-card" style="border-top: 3px solid {CLR_ALERT};">
        <div class="module-icon">🔔</div>
        <div class="module-title" style="color:{CLR_ALERT};">Alert Center{alert_badge}</div>
        <div class="module-sub">Sygnały rynkowe i anomalie<br>Office + Residential</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    if st.button("Otwórz Alerty →", key="btn_alerts", use_container_width=True):
        st.switch_page("pages/alerts.py")

with c4:
    try:
        from analytics import get_watchlist_listings
        n_watched = len(get_watchlist_listings())
    except Exception:
        n_watched = 0
    w_badge = f' <span class="alert-badge" style="background:#c9a84c;">{n_watched}</span>' if n_watched > 0 else ""
    st.markdown(f"""
    <div class="module-card" style="border-top: 3px solid {CLR_GOLD};">
        <div class="module-icon">⭐</div>
        <div class="module-title" style="color:{CLR_GOLD};">Watchlist{w_badge}</div>
        <div class="module-sub">Obserwowane oferty<br>Office + Residential</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    if st.button("Otwórz Watchlist →", key="btn_watchlist", use_container_width=True):
        st.switch_page("pages/watchlist.py")

# ──────────────────────────────────────────────
# OSTATNI LOG SCRAPERA
# ──────────────────────────────────────────────
st.markdown('<div style="border-top: 1px solid #2a2d35; margin: 40px 0 20px;"></div>', unsafe_allow_html=True)
with st.expander("📋 Log scrapera (ostatnie 10 runów)", expanded=False):
    try:
        log_df = get_scrape_log(10)
        if log_df.empty:
            st.info("Brak danych — uruchom najpierw scrapery.")
        else:
            st.dataframe(log_df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Błąd pobierania logu: {e}")
