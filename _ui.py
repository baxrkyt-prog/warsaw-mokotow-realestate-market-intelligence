"""
_ui.py — współdzielone style, motyw wykresów i helpery UI.
Ocean Plaza Market Intelligence.
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

# ──────────────────────────────────────────────
# KOLORY
# ──────────────────────────────────────────────
CLR_BG        = "#0d0f14"
CLR_SURFACE   = "#151820"
CLR_BORDER    = "#2a2d35"
CLR_TEXT      = "#e8eaf0"
CLR_MUTED     = "#7a7f8e"
CLR_GOLD      = "#c9a84c"  # Ocean Plaza
CLR_OFFICE    = "#4a8fb5"  # moduł biurowy
CLR_RESI      = "#50a870"  # moduł mieszkaniowy
CLR_ALERT     = "#e05c5c"
CLR_POSITIVE  = "#50a870"
CLR_NEGATIVE  = "#e05c5c"

HEALTH_COLORS = {
    "STRONG":    "#50a870",
    "STABLE":    "#c9a84c",
    "CAUTIOUS":  "#e0924a",
    "DISTRESSED":"#e05c5c",
}

# ──────────────────────────────────────────────
# MOTYW PLOTLY
# ──────────────────────────────────────────────
PLOT_THEME = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans, sans-serif", color=CLR_TEXT, size=12),
    xaxis=dict(gridcolor=CLR_BORDER, linecolor=CLR_BORDER, zerolinecolor=CLR_BORDER),
    yaxis=dict(gridcolor=CLR_BORDER, linecolor=CLR_BORDER, zerolinecolor=CLR_BORDER),
    margin=dict(l=40, r=20, t=30, b=40),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=CLR_BORDER),
    colorway=[CLR_OFFICE, CLR_GOLD, CLR_RESI, CLR_ALERT, CLR_MUTED],
)


def apply_plot_theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(**PLOT_THEME)
    return fig


# ──────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────
GLOBAL_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

html, body, [data-testid="stAppViewContainer"] {{
    background-color: {CLR_BG} !important;
    color: {CLR_TEXT};
    font-family: 'DM Sans', sans-serif;
}}

[data-testid="stSidebar"] {{ background-color: {CLR_SURFACE} !important; border-right: 1px solid {CLR_BORDER}; }}
[data-testid="stHeader"] {{ background-color: {CLR_BG} !important; }}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    background: {CLR_SURFACE};
    border-bottom: 1px solid {CLR_BORDER};
    gap: 0;
}}
.stTabs [data-baseweb="tab"] {{
    color: {CLR_MUTED};
    font-size: 13px;
    font-weight: 500;
    padding: 10px 20px;
    border-radius: 0;
    border: none;
    background: transparent;
}}
.stTabs [aria-selected="true"] {{
    color: {CLR_TEXT} !important;
    border-bottom: 2px solid {CLR_GOLD} !important;
    background: transparent !important;
}}

/* KPI card */
.kpi-card {{
    background: {CLR_SURFACE};
    border: 1px solid {CLR_BORDER};
    border-radius: 8px;
    padding: 16px 20px;
    height: 100%;
}}
.kpi-label {{
    font-size: 11px;
    font-weight: 600;
    color: {CLR_MUTED};
    text-transform: uppercase;
    letter-spacing: .06em;
    margin-bottom: 6px;
}}
.kpi-value {{
    font-size: 28px;
    font-weight: 700;
    color: {CLR_TEXT};
    font-family: 'DM Mono', monospace;
    line-height: 1.1;
}}
.kpi-delta-pos {{ font-size: 12px; color: {CLR_POSITIVE}; margin-top: 4px; }}
.kpi-delta-neg {{ font-size: 12px; color: {CLR_NEGATIVE}; margin-top: 4px; }}
.kpi-delta-neu {{ font-size: 12px; color: {CLR_MUTED}; margin-top: 4px; }}

/* Health score */
.health-ring {{
    display: flex; align-items: center; gap: 16px;
    padding: 16px; background: {CLR_SURFACE};
    border: 1px solid {CLR_BORDER}; border-radius: 10px;
    margin-bottom: 16px;
}}
.health-score-num {{
    font-size: 48px; font-weight: 700;
    font-family: 'DM Mono', monospace; line-height: 1;
}}
.health-label {{
    font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .1em;
}}
.health-sub {{ font-size: 12px; color: {CLR_MUTED}; margin-top: 2px; }}

/* Module cards (Home) */
.module-card {{
    background: {CLR_SURFACE};
    border: 1px solid {CLR_BORDER};
    border-radius: 12px;
    padding: 28px;
    cursor: pointer;
    transition: border-color .15s, transform .15s;
    text-align: center;
}}
.module-card:hover {{ border-color: {CLR_GOLD}; transform: translateY(-2px); }}
.module-icon {{ font-size: 40px; margin-bottom: 12px; }}
.module-title {{ font-size: 18px; font-weight: 700; color: {CLR_TEXT}; }}
.module-sub {{ font-size: 13px; color: {CLR_MUTED}; margin-top: 6px; }}

/* Data tables */
[data-testid="stDataFrame"] {{ background: {CLR_SURFACE}; border-radius: 8px; }}

/* Alert badge */
.alert-badge {{
    display: inline-block;
    background: {CLR_ALERT};
    color: white;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 10px;
    margin-left: 6px;
    vertical-align: middle;
}}

/* Divider */
.mi-divider {{ border-top: 1px solid {CLR_BORDER}; margin: 20px 0; }}
</style>
"""


def inject_css():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def lifecycle_flag(dom_days, is_active: bool, median_dom: int = 60) -> str:
    """Flaga wizualna stanu oferty: 🟢 New / 🟡 Active / 🟠 Aging / 🔴 Stale / ⚫ Delisted."""
    if not is_active:
        return "⚫ Delisted"
    if dom_days is None:
        return "🟡 Active"
    if dom_days <= 30:
        return "🟢 New"
    if dom_days >= median_dom * 2:
        return "🔴 Stale"
    if dom_days >= median_dom:
        return "🟠 Aging"
    return "🟡 Active"


def has_demo_transactions() -> bool:
    """True jeśli w bazie są poglądowe (nie-realne) dane transakcyjne."""
    try:
        from database import get_conn
        with get_conn() as c:
            r = c.execute(
                "SELECT COUNT(*) n FROM transactions "
                "WHERE source LIKE 'demo%' OR source LIKE 'fixture%'"
            ).fetchone()
        return (r["n"] or 0) > 0
    except Exception:
        return False


def demo_banner(context: str = "dane transakcyjne"):
    """Spójne ostrzeżenie: pokazywane wartości oparte są na danych DEMO (poglądowych)."""
    if not has_demo_transactions():
        return
    st.markdown(
        f'<div style="background:#2a2410;border:1px solid #c9a84c;border-radius:6px;'
        f'padding:8px 14px;margin-bottom:14px;font-size:12px;color:#c9a84c;">'
        f'⚠️ <b>DANE DEMO</b> — {context} oparte na zbiorze poglądowym (syntetycznym), '
        f'nie na realnym rejestrze transakcji. Nie wyciągaj wniosków inwestycyjnych z tych liczb.'
        f'</div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────
# KOMPONENTY
# ──────────────────────────────────────────────

def kpi_card(label: str, value, unit: str = "", delta=None, inverse: bool = False):
    """Renderuje kartę KPI jako HTML."""
    val_str = f"{value:,.0f}" if isinstance(value, float) and value >= 100 else (
        f"{value:.2f}" if isinstance(value, float) else str(value) if value is not None else "—"
    )

    delta_html = ""
    if delta is not None:
        arrow = "▲" if delta > 0 else "▼"
        good  = (delta > 0 and not inverse) or (delta < 0 and inverse)
        cls   = "kpi-delta-pos" if good else "kpi-delta-neg"
        delta_html = f'<div class="{cls}">{arrow} {abs(delta):.1f}% m/m</div>'
    else:
        delta_html = f'<div class="kpi-delta-neu">—</div>'

    html = f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{val_str}</div>
        <div style="font-size:11px;color:#7a7f8e;margin-top:2px;">{unit}</div>
        {delta_html}
    </div>"""
    st.markdown(html, unsafe_allow_html=True)


def insight_card(label: str, value, unit: str = "", delta=None,
                 inverse: bool = False, interpretation: str = "",
                 window: str = "90d"):
    """Karta KPI z interpretacją: wartość + kierunek + zmiana + 1-zdaniowy sens.

    delta: % zmiana (None = brak danych porównawczych).
    inverse: True gdy spadek jest dobry (np. liczba ofert konkurencji).
    interpretation: krótki tekst "co to znaczy" (opcjonalny).
    """
    val_str = f"{value:,.0f}".replace(",", " ") if isinstance(value, (int, float)) and abs(value) >= 100 else (
        f"{value:.2f}" if isinstance(value, float) else str(value) if value is not None else "—"
    )

    if delta is not None:
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        good = (delta > 0 and not inverse) or (delta < 0 and inverse)
        color = CLR_POSITIVE if good else (CLR_NEGATIVE if delta != 0 else CLR_MUTED)
        delta_html = (f'<span style="color:{color};font-size:13px;font-weight:600;">'
                      f'{arrow} {abs(delta):.1f}% <span style="color:{CLR_MUTED};font-weight:400;">vs {window}</span></span>')
    else:
        delta_html = f'<span style="color:{CLR_MUTED};font-size:12px;">brak danych porównawczych</span>'

    interp_html = (f'<div style="font-size:11px;color:{CLR_MUTED};margin-top:8px;line-height:1.4;">{interpretation}</div>'
                   if interpretation else "")

    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{val_str}<span style="font-size:13px;color:{CLR_MUTED};font-weight:400;font-family:'DM Sans';"> {unit}</span></div>
        <div style="margin-top:6px;">{delta_html}</div>
        {interp_html}
    </div>""", unsafe_allow_html=True)


def health_score_widget(data: dict, module_color: str = CLR_GOLD):
    """Renderuje blok Market Health Score."""
    score  = data.get("score", 0)
    label  = data.get("label", "—")
    color  = HEALTH_COLORS.get(label, CLR_GOLD)
    comps  = data.get("components", {})

    st.markdown(f"""
    <div class="health-ring">
        <div>
            <div class="health-score-num" style="color:{color};">{score}</div>
            <div class="health-label" style="color:{color};">{label}</div>
            <div class="health-sub">Market Health Score / 100</div>
        </div>
        <div style="flex:1;">
            {''.join(
                f'<div style="margin-bottom:6px;">'
                f'<div style="font-size:11px;color:#7a7f8e;margin-bottom:2px;">{k}</div>'
                f'<div style="background:#2a2d35;border-radius:4px;height:6px;">'
                f'<div style="width:{v/25*100:.0f}%;background:{color};height:100%;border-radius:4px;"></div>'
                f'</div></div>'
                for k, v in comps.items()
            )}
        </div>
    </div>
    """, unsafe_allow_html=True)


def section_header(title: str, subtitle: str = ""):
    st.markdown(f"""
    <div style="margin: 24px 0 12px;">
        <div style="font-size:15px;font-weight:700;color:{CLR_TEXT};">{title}</div>
        {'<div style="font-size:12px;color:#7a7f8e;margin-top:2px;">'+subtitle+'</div>' if subtitle else ''}
    </div>""", unsafe_allow_html=True)


def divider():
    st.markdown('<div class="mi-divider"></div>', unsafe_allow_html=True)


def listing_table(df: pd.DataFrame, key: str, url_col: str = "url",
                  watched_ids: set = None, show_cols: list = None):
    """
    Renderuje tabelę ofert z:
    - klikalnymi linkami (LinkColumn)
    - checkboxem 'Obserwuj' (data_editor)
    Zwraca set offer_id zaznaczonych do obserwacji po edycji.
    """
    import streamlit as st
    from analytics import bulk_set_watchlist

    if df is None or df.empty:
        st.info("Brak ofert do wyświetlenia.")
        return set()

    if watched_ids is None:
        watched_ids = set()

    work = df.copy()

    # Kolumna watchlist — dodaj PRZED filtrowaniem show_cols
    work["⭐ Obserwuj"] = work["offer_id"].isin(watched_ids)

    # Δ cena od obserwacji — wzbogać dla obserwowanych ofert jeśli brak kolumny
    if "Δ cena od obserwacji" not in work.columns and len(watched_ids) > 0:
        from analytics import get_watchlist_listings
        import pandas as _pd
        try:
            wl = get_watchlist_listings()[["offer_id", "price_at_add", "current_price", "price_change", "price_change_pct"]]
            work = work.merge(wl, on="offer_id", how="left")

            def _fmt(row):
                if not row["⭐ Obserwuj"] or _pd.isna(row.get("price_change")) or _pd.isna(row.get("price_at_add")):
                    return ""
                chg = row["price_change"]
                pct = row["price_change_pct"]
                sign = "+" if chg > 0 else ""
                return f"{sign}{chg:,.0f} zł ({sign}{pct:.1f}%)"

            work["Δ cena"] = work.apply(_fmt, axis=1)
        except Exception:
            pass

    # Domyślne kolumny jeśli nie podano
    if show_cols is None:
        candidates = [
            "⭐ Obserwuj", "title", url_col, "subdistrict", "building_name",
            "area_m2", "rooms", "floor", "price_total", "price_per_m2",
            "Δ cena", "advertiser_type", "is_active", "first_seen",
        ]
        show_cols = [c for c in candidates if c in work.columns]

    # Filtruj show_cols do kolumn faktycznie dostępnych w work (po dodaniu Δ cena itp.)
    show_cols = [c for c in show_cols if c in work.columns]
    display = work[show_cols].copy()

    # Konfiguracja kolumn
    col_cfg = {}

    if url_col in display.columns:
        col_cfg[url_col] = st.column_config.LinkColumn(
            "🔗 Link", display_text="Otwórz →", width="small"
        )

    if "⭐ Obserwuj" in display.columns:
        col_cfg["⭐ Obserwuj"] = st.column_config.CheckboxColumn(
            "⭐", width="small", help="Dodaj do listy obserwowanych"
        )

    rename = {
        "title":           "Tytuł",
        "subdistrict":     "Dzielnica",
        "building_name":   "Budynek",
        "area_m2":         "Pow. m²",
        "rooms":           "Pokoje",
        "floor":           "Piętro",
        "price_total":     "Cena PLN",
        "price_per_m2":    "PLN/m²",
        "advertiser_type": "Wystawiający",
        "is_active":       "Aktywna",
        "first_seen":      "Od kiedy",
        "asset_class":     "Typ",
        "price_at_add":    "Cena przy dodaniu",
        "current_price":   "Cena aktualna",
        "added_ts":        "Dodano",
    }
    display = display.rename(columns={k: v for k, v in rename.items() if k in display.columns})

    # Zaktualizuj col_cfg po rename
    if url_col in col_cfg:
        pass  # url_col nie jest w rename, zostaje
    if "⭐ Obserwuj" in col_cfg:
        pass  # zostaje

    edited = st.data_editor(
        display,
        key=key,
        use_container_width=True,
        hide_index=True,
        column_config=col_cfg,
        disabled=[c for c in display.columns if c != "⭐ Obserwuj"],
        num_rows="fixed",
    )

    # Wykryj zmiany watchlist i zapisz do DB
    orig_watched = set(work.loc[work["⭐ Obserwuj"], "offer_id"].tolist())
    new_watched  = set(work.loc[edited["⭐ Obserwuj"].values, "offer_id"].tolist()) if "⭐ Obserwuj" in edited.columns else orig_watched

    to_add    = new_watched - orig_watched
    to_remove = orig_watched - new_watched
    if to_add or to_remove:
        bulk_set_watchlist(list(to_add), list(to_remove))
        st.toast(
            f"{'➕ Dodano: ' + str(len(to_add)) if to_add else ''}"
            f"{'  🗑 Usunięto: ' + str(len(to_remove)) if to_remove else ''}".strip(),
            icon="⭐",
        )

    return new_watched


def page_header(title: str, subtitle: str = "", color: str = CLR_GOLD):
    st.markdown(f"""
    <div style="padding: 20px 0 8px;">
        <div style="font-size:26px;font-weight:700;color:{color};">{title}</div>
        {'<div style="font-size:14px;color:#7a7f8e;margin-top:4px;">'+subtitle+'</div>' if subtitle else ''}
    </div>
    <div style="border-bottom: 1px solid #2a2d35; margin-bottom: 20px;"></div>
    """, unsafe_allow_html=True)
