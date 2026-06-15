"""
pages/transactions.py — DEPRECATED.

Stary moduł "Ceny Transakcyjne" (oparty na danych demo/RCN) został zastąpiony przez
**Market Liquidity & Pricing** (pages/pricing_intelligence.py), który estymuje ceny
transakcyjne z danych ofertowych. Ta strona przekierowuje do nowego modułu.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from _ui import inject_css, page_header, CLR_GOLD, CLR_MUTED

st.set_page_config(page_title="Transactions → Market Liquidity & Pricing",
                   page_icon="📊", layout="wide", initial_sidebar_state="collapsed")
inject_css()

page_header("Moduł przeniesiony", "Ceny Transakcyjne → Market Liquidity & Pricing", color=CLR_GOLD)
st.info("Moduł cen transakcyjnych został zastąpiony przez **Market Liquidity & Pricing** — "
        "ceny transakcyjne są teraz **estymowane z danych ofertowych** (zero danych demo/RCN).")
if st.button("→ Przejdź do Market Liquidity & Pricing", use_container_width=True):
    st.switch_page("pages/pricing_intelligence.py")
if st.button("← Home", use_container_width=True):
    st.switch_page("app.py")
