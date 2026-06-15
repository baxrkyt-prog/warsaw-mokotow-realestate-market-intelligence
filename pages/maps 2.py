"""
pages/maps.py — moduł map (Phase 6 / UX Phase 8).

Jeden moduł, przełączane warstwy (toggle) zamiast osobnych stron:
  • Asking heatmap       — gęstość cen ofertowych (PLN/m²)
  • Transaction heatmap  — gęstość cen transakcyjnych (PLN/m²)
  • Spread              — centroidy dzielnic, kolor zielony→czerwony wg spreadu

Plotly density_mapbox / scatter_mapbox ze stylem open-street-map (bez tokena, zero kosztów).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from database import get_conn, OCEAN_PLAZA_LAT, OCEAN_PLAZA_LON
from analytics import get_spread_table
from _ui import (
    inject_css, page_header, section_header, demo_banner,
    CLR_GOLD, CLR_TEXT, CLR_MUTED, CLR_BORDER, CLR_SURFACE,
)

st.set_page_config(
    page_title="Maps · Ocean Plaza MI",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()

if st.button("← Home", key="back_home"):
    st.switch_page("app.py")

page_header("Market Maps", "Geoprzestrzenny obraz rynku — przełączaj warstwy", color=CLR_GOLD)

demo_banner("warstwy transakcyjne i spread")


@st.cache_data(ttl=180)
def load_listings_geo():
    with get_conn() as c:
        return pd.read_sql_query("""
            SELECT latitude, longitude, price_per_m2, subdistrict, area_m2,
                   geocode_confidence
            FROM listings
            WHERE is_active=1 AND asset_class='residential'
              AND transaction_type IN ('sale','invest_unit')
              AND latitude IS NOT NULL AND price_per_m2 IS NOT NULL
        """, c)


@st.cache_data(ttl=180)
def load_tx_geo():
    with get_conn() as c:
        return pd.read_sql_query("""
            SELECT latitude, longitude, transaction_price_per_m2 as price_per_m2,
                   district_norm, area_m2, geocode_confidence, transaction_date
            FROM transactions
            WHERE latitude IS NOT NULL AND transaction_price_per_m2 IS NOT NULL
        """, c)


@st.cache_data(ttl=180)
def load_district_centroids():
    with get_conn() as c:
        return pd.read_sql_query("""
            SELECT district_norm, display_name, center_lat, center_lon
            FROM geo_districts WHERE center_lat IS NOT NULL
        """, c)


# ── Toggle warstwy + filtr ─────────────────────
c1, c2 = st.columns([2, 1])
with c1:
    layer = st.radio(
        "Warstwa",
        options=["Asking (oferty)", "Transaction (transakcje)", "Spread (luka cenowa)"],
        horizontal=True,
    )
with c2:
    min_conf = st.select_slider(
        "Min. pewność geo", options=[0.0, 0.5, 0.7, 1.0], value=0.5,
        format_func=lambda v: {0.0: "wszystkie", 0.5: "≥0.5 centroid",
                               0.7: "≥0.7 ulica", 1.0: "1.0 punkt"}[v])

CENTER = dict(lat=OCEAN_PLAZA_LAT, lon=OCEAN_PLAZA_LON)
MAP_STYLE = "open-street-map"


def _ocean_plaza_marker(fig):
    fig.add_trace(go.Scattermapbox(
        lat=[OCEAN_PLAZA_LAT], lon=[OCEAN_PLAZA_LON],
        mode="markers+text", marker=dict(size=16, color=CLR_GOLD),
        text=["Ocean Plaza"], textposition="top center",
        textfont=dict(color=CLR_GOLD, size=13), name="Ocean Plaza",
        hovertext="Ocean Plaza · Domaniewska 50", hoverinfo="text",
    ))


if layer.startswith("Asking"):
    df = load_listings_geo()
    df = df[df["geocode_confidence"].fillna(0) >= min_conf]
    section_header("Asking Heatmap", f"ceny ofertowe sprzedaży · {len(df)} ofert")
    if df.empty:
        st.info("Brak ofert z geokodowaniem w wybranym progu pewności.")
    else:
        fig = px.density_mapbox(
            df, lat="latitude", lon="longitude", z="price_per_m2",
            radius=22, center=CENTER, zoom=11.5, mapbox_style=MAP_STYLE,
            color_continuous_scale="YlOrRd",
            labels={"price_per_m2": "PLN/m²"},
        )
        _ocean_plaza_marker(fig)
        fig.update_layout(height=620, margin=dict(l=0, r=0, t=0, b=0),
                          paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Gęstość ważona ceną ofertową PLN/m². Ciemniejsze = drożej.")

elif layer.startswith("Transaction"):
    df = load_tx_geo()
    df = df[df["geocode_confidence"].fillna(0) >= min_conf]
    section_header("Transaction Heatmap", f"ceny transakcyjne · {len(df)} transakcji")
    if df.empty:
        st.info("Brak transakcji z geokodowaniem w wybranym progu pewności.")
    else:
        fig = px.density_mapbox(
            df, lat="latitude", lon="longitude", z="price_per_m2",
            radius=25, center=CENTER, zoom=11.5, mapbox_style=MAP_STYLE,
            color_continuous_scale="YlGnBu",
            labels={"price_per_m2": "PLN/m²"},
        )
        _ocean_plaza_marker(fig)
        fig.update_layout(height=620, margin=dict(l=0, r=0, t=0, b=0),
                          paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Gęstość ważona ceną transakcyjną PLN/m² (dane RCN/demo).")

else:  # Spread
    section_header("Spread — luka ofertowo-transakcyjna",
                   "centroidy dzielnic · zielony = mały spread, czerwony = duży")
    spread = get_spread_table("residential", 90)
    cent = load_district_centroids()
    if spread.empty:
        st.info("Brak zmaterializowanych spreadów per dzielnica (potrzeba ≥3 transakcji/dzielnicę).")
    else:
        cent_min = cent[["district_norm", "center_lat", "center_lon"]]
        m = spread.merge(cent_min, on="district_norm", how="left")
        m = m[m["center_lat"].notna()]
        if m.empty:
            st.info("Brak centroidów dla dzielnic ze spreadem.")
        else:
            m["abs_spread"] = m["spread_pct"].abs().clip(lower=0.5)
            fig = px.scatter_mapbox(
                m, lat="center_lat", lon="center_lon",
                size="abs_spread", color="spread_pct",
                color_continuous_scale="RdYlGn_r",
                size_max=40, center=CENTER, zoom=11.5, mapbox_style=MAP_STYLE,
                hover_name="display_name",
                custom_data=["spread_pct", "n_transactions"],
            )
            fig.update_traces(hovertemplate="<b>%{hovertext}</b><br>Spread: %{customdata[0]:.1f}%"
                                            "<br>Transakcje: %{customdata[1]}<extra></extra>")
            _ocean_plaza_marker(fig)
            fig.update_layout(height=560, margin=dict(l=0, r=0, t=0, b=0),
                              paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Rozmiar = wielkość |spreadu|, kolor: zielony (oferty≈transakcje) → "
                       "czerwony (duża luka). Spread ujemny = transakcje poniżej ofert.")
