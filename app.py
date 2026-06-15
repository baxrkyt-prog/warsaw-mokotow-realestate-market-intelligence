"""
app.py — Ocean Plaza Intelligence Center (homepage).

Zasada UX: 15-second overview. Hierarchia informacji:
  1. Market Snapshot (4 score cards)   — co się dzieje?
  2. What Changed                       — co się zmieniło?
  3. Ocean Plaza Zone                   — co wokół aktywa?
  4. Market Narrative + Brief           — co to znaczy?
  5. Nawigacja do modułów               — gdzie pogłębić?
Surowe tabele i wykresy żyją w modułach, nie na landing page.
"""

import streamlit as st

from analytics import (
    compute_office_health_score, compute_residential_health_score,
    compute_liquidity_score, compute_pricing_pressure_score,
    get_what_changed, get_zone_intelligence,
    generate_market_narrative, generate_market_brief, generate_market_brief_pdf,
    get_alerts, get_last_scrape_ts,
)
from _ui import (
    inject_css, HEALTH_COLORS, demo_banner,
    CLR_GOLD, CLR_OFFICE, CLR_RESI, CLR_ALERT,
    CLR_TEXT, CLR_MUTED, CLR_BORDER, CLR_SURFACE,
)

st.set_page_config(
    page_title="Ocean Plaza · Intelligence Center",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()

# ──────────────────────────────────────────────
# DATA (cache 5 min — homepage ma być szybki)
# ──────────────────────────────────────────────

@st.cache_data(ttl=300)
def _load_intelligence():
    return {
        "office": compute_office_health_score(),
        "residential": compute_residential_health_score(),
        "liquidity": compute_liquidity_score("residential"),
        "pressure": compute_pricing_pressure_score("residential"),
        "changed": get_what_changed(),
        "zone": get_zone_intelligence(),
        "narrative": generate_market_narrative(),
        "last_scrape": get_last_scrape_ts(),
    }

data = _load_intelligence()

try:
    n_alerts = len(get_alerts(unread_only=True))
except Exception:
    n_alerts = 0

# ──────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────
col_logo, col_ts = st.columns([3, 1])
with col_logo:
    st.markdown(f"""
    <div style="padding: 20px 0 4px;">
        <div style="font-size:11px;font-weight:600;color:{CLR_MUTED};letter-spacing:.1em;text-transform:uppercase;">
            Ocean Plaza · ul. Domaniewska 50, Mokotów
        </div>
        <div style="font-size:30px;font-weight:700;color:{CLR_GOLD};margin-top:2px;">
            Intelligence Center
        </div>
    </div>
    """, unsafe_allow_html=True)
with col_ts:
    st.markdown(f'<div style="font-size:11px;color:{CLR_MUTED};text-align:right;padding-top:34px;">'
                f'Ostatnia aktualizacja<br><b style="color:{CLR_TEXT};">{data["last_scrape"]}</b></div>',
                unsafe_allow_html=True)

st.markdown(f'<div style="border-bottom:1px solid {CLR_BORDER};margin-bottom:24px;"></div>',
            unsafe_allow_html=True)

demo_banner("wskaźniki transakcyjne, liquidity i pricing pressure")

# ──────────────────────────────────────────────
# 1. MARKET SNAPSHOT — 4 duże karty score
# ──────────────────────────────────────────────

def snapshot_card(title: str, icon: str, score, label: str, sub: str, accent: str):
    color = HEALTH_COLORS.get(label, CLR_MUTED)
    score_disp = str(score) if score is not None else "—"
    label_disp = label if score is not None else "BRAK DANYCH"
    st.markdown(f"""
    <div style="background:{CLR_SURFACE};border:1px solid {CLR_BORDER};border-top:3px solid {accent};
                border-radius:10px;padding:20px 22px;height:100%;">
        <div style="font-size:11px;font-weight:600;color:{CLR_MUTED};letter-spacing:.08em;
                    text-transform:uppercase;">{icon} {title}</div>
        <div style="display:flex;align-items:baseline;gap:10px;margin:10px 0 6px;">
            <span style="font-size:42px;font-weight:700;color:{color};line-height:1;">{score_disp}</span>
            <span style="font-size:14px;color:{CLR_MUTED};">/100</span>
        </div>
        <div style="font-size:13px;font-weight:700;color:{color};letter-spacing:.05em;">{label_disp}</div>
        <div style="font-size:11px;color:{CLR_MUTED};margin-top:6px;">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


o, r = data["office"], data["residential"]
liq, pp = data["liquidity"], data["pressure"]

c1, c2, c3, c4 = st.columns(4, gap="medium")
with c1:
    top = max(o["components"], key=o["components"].get)
    snapshot_card("Office Market", "🏢", o["score"], o["label"],
                  f"najmocniejszy komponent: {top}", CLR_OFFICE)
with c2:
    top = max(r["components"], key=r["components"].get)
    snapshot_card("Residential Market", "🏠", r["score"], r["label"],
                  f"najmocniejszy komponent: {top}", CLR_RESI)
with c3:
    sub = (f"{liq['inputs']['tx_count']} transakcji / 30d" if liq.get("inputs") else
           liq.get("reason", ""))
    snapshot_card("Transaction Liquidity", "💼", liq["score"], liq["label"], sub, CLR_GOLD)
with c4:
    sub = f"spread: {pp['inputs']['spread_pct']}%" if pp["inputs"].get("spread_pct") is not None else "spread: n/d"
    snapshot_card("Pricing Pressure", "📐", pp["score"], pp["label"], sub, CLR_ALERT)

if n_alerts:
    st.markdown(f"""
    <div style="background:#2d1a1a;border:1px solid {CLR_ALERT};border-radius:8px;
                padding:10px 18px;margin-top:16px;font-size:13px;">
        🔔 <b style="color:{CLR_ALERT};">{n_alerts} nieprzeczytanych alertów</b>
        <span style="color:{CLR_MUTED};"> — szczegóły w Alert Center</span>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# 2. WHAT CHANGED
# ──────────────────────────────────────────────
left, right = st.columns([1.15, 1], gap="large")

with left:
    st.markdown(f'<div style="font-size:15px;font-weight:700;color:{CLR_TEXT};margin-bottom:4px;">'
                f'Co się zmieniło</div>'
                f'<div style="font-size:11px;color:{CLR_MUTED};margin-bottom:12px;">'
                f'sygnały posortowane wg istotności biznesowej</div>', unsafe_allow_html=True)
    changed = data["changed"]
    if not changed:
        st.markdown(f'<div style="color:{CLR_MUTED};font-size:13px;">Brak istotnych zmian '
                    f'w bieżącym oknie danych.</div>', unsafe_allow_html=True)
    for e in changed:
        st.markdown(f"""
        <div style="background:{CLR_SURFACE};border:1px solid {CLR_BORDER};border-radius:8px;
                    padding:10px 16px;margin-bottom:8px;display:flex;gap:12px;align-items:baseline;">
            <span style="font-size:15px;">{e['icon']}</span>
            <div>
                <div style="font-size:13px;font-weight:600;color:{CLR_TEXT};">{e['title']}</div>
                <div style="font-size:11px;color:{CLR_MUTED};">{e['detail']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ──────────────────────────────────────────────
# 3. OCEAN PLAZA ZONE
# ──────────────────────────────────────────────
with right:
    st.markdown(f'<div style="font-size:15px;font-weight:700;color:{CLR_TEXT};margin-bottom:4px;">'
                f'Ocean Plaza Zone</div>'
                f'<div style="font-size:11px;color:{CLR_MUTED};margin-bottom:12px;">'
                f'rynek mieszkaniowy w promieniu od aktywa · okno 180 dni</div>',
                unsafe_allow_html=True)
    zone = data["zone"]

    hdr = f"""<tr style="color:{CLR_MUTED};font-size:10px;text-transform:uppercase;letter-spacing:.06em;">
        <th style="text-align:left;padding:6px 10px;">Strefa</th>
        <th style="text-align:right;padding:6px 10px;">Asking</th>
        <th style="text-align:right;padding:6px 10px;">Transaction</th>
        <th style="text-align:right;padding:6px 10px;">Spread</th>
        <th style="text-align:right;padding:6px 10px;">Tx</th>
        <th style="text-align:right;padding:6px 10px;">Oferty</th></tr>"""
    rows_html = ""
    for _, z in zone.iterrows():
        def f(v, fmt="{:,.0f}"):
            return fmt.format(v).replace(",", " ") if v is not None and v == v else "—"
        spread_v = z["spread_pct"]
        spread_color = (CLR_ALERT if (spread_v is not None and spread_v == spread_v and spread_v < -10)
                        else CLR_RESI if (spread_v is not None and spread_v == spread_v and spread_v > 0)
                        else CLR_TEXT)
        spread_disp = f"{spread_v:+.1f}%" if spread_v is not None and spread_v == spread_v else "—"
        rows_html += f"""<tr style="font-size:12px;color:{CLR_TEXT};border-top:1px solid {CLR_BORDER};">
            <td style="padding:8px 10px;font-weight:700;color:{CLR_GOLD};">{z['zone_label']}</td>
            <td style="text-align:right;padding:8px 10px;">{f(z['median_asking'])}</td>
            <td style="text-align:right;padding:8px 10px;">{f(z['median_transaction'])}</td>
            <td style="text-align:right;padding:8px 10px;color:{spread_color};font-weight:600;">{spread_disp}</td>
            <td style="text-align:right;padding:8px 10px;">{int(z['tx_count'])}</td>
            <td style="text-align:right;padding:8px 10px;">{int(z['active_listings'])}</td></tr>"""
    st.markdown(f"""
    <div style="background:{CLR_SURFACE};border:1px solid {CLR_BORDER};border-radius:8px;overflow:hidden;">
        <table style="width:100%;border-collapse:collapse;">{hdr}{rows_html}</table>
        <div style="font-size:10px;color:{CLR_MUTED};padding:8px 10px;border-top:1px solid {CLR_BORDER};">
            PLN/m² · strefy kumulatywne · transakcje wymagają ≥3 obserwacji (inaczej "—")
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 4. Market Narrative
    st.markdown(f"""
    <div style="background:{CLR_SURFACE};border-left:3px solid {CLR_GOLD};border-radius:6px;
                padding:14px 18px;margin-top:16px;">
        <div style="font-size:10px;font-weight:700;color:{CLR_MUTED};text-transform:uppercase;
                    letter-spacing:.08em;margin-bottom:6px;">Market Narrative</div>
        <div style="font-size:13px;color:{CLR_TEXT};line-height:1.55;">{data['narrative']}</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("📄 Generate Market Brief", key="brief_btn", use_container_width=True):
        st.session_state["brief_ready"] = True

    if st.session_state.get("brief_ready"):
        brief_md = generate_market_brief()
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "⬇️ Markdown", data=brief_md,
                file_name="ocean_plaza_market_brief.md",
                mime="text/markdown", use_container_width=True,
            )
        with dl2:
            try:
                brief_pdf = generate_market_brief_pdf()
                st.download_button(
                    "⬇️ PDF", data=brief_pdf,
                    file_name="ocean_plaza_market_brief.pdf",
                    mime="application/pdf", use_container_width=True,
                )
            except Exception as e:
                st.caption(f"PDF niedostępny: {e}")
        with st.expander("Podgląd briefu", expanded=True):
            st.markdown(brief_md)

st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
st.markdown(f'<div style="border-top:1px solid {CLR_BORDER};margin-bottom:18px;"></div>',
            unsafe_allow_html=True)

# ──────────────────────────────────────────────
# 5. NAWIGACJA DO MODUŁÓW
# ──────────────────────────────────────────────
st.markdown(f'<div style="font-size:11px;color:{CLR_MUTED};text-transform:uppercase;'
            f'letter-spacing:.08em;margin-bottom:10px;">Moduły analityczne</div>',
            unsafe_allow_html=True)

nav_cols = st.columns(7, gap="small")
NAV = [
    (nav_cols[0], "🏢 Office", "pages/office.py"),
    (nav_cols[1], "🏠 Residential", "pages/residential.py"),
    (nav_cols[2], "📊 Liquidity & Pricing", "pages/pricing_intelligence.py"),
    (nav_cols[3], "🔄 Lifecycle", "pages/lifecycle.py"),
    (nav_cols[4], "🗺️ Maps", "pages/maps.py"),
    (nav_cols[5], f"🔔 Alerty{f' ({n_alerts})' if n_alerts else ''}", "pages/alerts.py"),
    (nav_cols[6], "⭐ Watchlist", "pages/watchlist.py"),
]
for col, label, page in NAV:
    with col:
        if st.button(label, key=f"nav_{page}", use_container_width=True):
            st.switch_page(page)
