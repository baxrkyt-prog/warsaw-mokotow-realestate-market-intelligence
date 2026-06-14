"""
analytics/narrative.py — Market Narrative Engine + What Changed.

Wszystkie teksty generowane DETERMINISTYCZNIE z realnych metryk — zero
halucynacji: każde zdanie ma źródło w konkretnym zapytaniu. Brak danych
= brak zdania (nie zmyślamy).

What Changed: zdarzenia z priorytetem severity:
  3 = critical (czerwone)  — wymaga reakcji
  2 = warning  (bursztyn)  — obserwować
  1 = positive (zielone)   — sprzyjające
  0 = info     (szare)     — kontekst
"""

from __future__ import annotations

from datetime import datetime, timezone

from database import get_conn
from .confidence import SUPPRESS


def _pct(curr, prev) -> float | None:
    if curr is None or prev is None or not prev:
        return None
    return (curr - prev) / prev * 100


def _office_deltas(conn) -> dict:
    r = conn.execute("""
        SELECT
            AVG(CASE WHEN s.scrape_date >= date('now','-14 days') THEN s.current_price_m2 END) as rent_now,
            AVG(CASE WHEN s.scrape_date BETWEEN date('now','-44 days') AND date('now','-15 days') THEN s.current_price_m2 END) as rent_prev
        FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
        WHERE l.asset_class='office' AND s.current_price_m2 IS NOT NULL
    """).fetchone()
    sup = conn.execute("""
        SELECT
            COUNT(CASE WHEN is_active=1 THEN 1 END) as active_now,
            COUNT(CASE WHEN first_seen >= date('now','-30 days') THEN 1 END) as new_30,
            COUNT(CASE WHEN is_active=0 AND last_seen >= date('now','-30 days') THEN 1 END) as absorbed_30,
            COUNT(CASE WHEN first_seen BETWEEN date('now','-60 days') AND date('now','-31 days') THEN 1 END) as new_prev
        FROM listings WHERE asset_class='office'
    """).fetchone()
    return {
        "rent_chg": _pct(r["rent_now"], r["rent_prev"]),
        "active": sup["active_now"], "new_30": sup["new_30"],
        "absorbed_30": sup["absorbed_30"],
        "supply_chg": _pct(sup["new_30"], sup["new_prev"]),
    }


def _residential_deltas(conn) -> dict:
    r = conn.execute("""
        SELECT
            AVG(CASE WHEN s.scrape_date >= date('now','-14 days') THEN s.current_price_m2 END) as p_now,
            AVG(CASE WHEN s.scrape_date BETWEEN date('now','-44 days') AND date('now','-15 days') THEN s.current_price_m2 END) as p_prev
        FROM snapshots s JOIN listings l ON l.offer_id=s.offer_id
        WHERE l.asset_class='residential' AND l.transaction_type='sale'
          AND s.current_price_m2 IS NOT NULL
    """).fetchone()
    v = conn.execute("""
        SELECT
            COUNT(CASE WHEN is_active=0 AND last_seen >= date('now','-30 days') THEN 1 END) as sold_30,
            COUNT(CASE WHEN is_active=0 AND last_seen BETWEEN date('now','-60 days') AND date('now','-31 days') THEN 1 END) as sold_prev,
            COUNT(CASE WHEN is_active=1 THEN 1 END) as active
        FROM listings WHERE asset_class='residential' AND transaction_type IN ('sale','invest_unit')
    """).fetchone()
    return {
        "price_chg": _pct(r["p_now"], r["p_prev"]),
        "velocity_chg": _pct(v["sold_30"], v["sold_prev"]),
        "sold_30": v["sold_30"], "active": v["active"],
    }


def _transaction_deltas(conn) -> dict:
    t = conn.execute("""
        SELECT
            COUNT(CASE WHEN transaction_date >= date('now','-30 days') THEN 1 END) as tx_30,
            COUNT(CASE WHEN transaction_date BETWEEN date('now','-60 days') AND date('now','-31 days') THEN 1 END) as tx_prev,
            AVG(CASE WHEN transaction_date >= date('now','-90 days') THEN transaction_price_per_m2 END) as px_now,
            AVG(CASE WHEN transaction_date BETWEEN date('now','-180 days') AND date('now','-91 days') THEN transaction_price_per_m2 END) as px_prev
        FROM transactions WHERE property_type='residential'
    """).fetchone()
    return {
        "tx_30": t["tx_30"], "tx_prev": t["tx_prev"],
        "volume_chg": _pct(t["tx_30"], t["tx_prev"]),
        "price_chg": _pct(t["px_now"], t["px_prev"]),
    }


def _spread_deltas(conn) -> dict:
    rows = conn.execute("""
        SELECT snapshot_date, AVG(spread_pct) as s
        FROM pricing_spreads
        WHERE property_type='residential' AND window_days=90 AND district_norm != ''
        GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 2
    """).fetchall()
    curr = rows[0]["s"] if rows else None
    prev = rows[1]["s"] if len(rows) > 1 else None
    return {"spread_now": curr, "spread_prev": prev,
            "spread_chg": (curr - prev) if (curr is not None and prev is not None) else None}


def get_market_deltas() -> dict:
    """Wspólny zestaw delt dla What Changed / narrative / snapshot cards."""
    with get_conn() as conn:
        return {
            "office": _office_deltas(conn),
            "residential": _residential_deltas(conn),
            "transactions": _transaction_deltas(conn),
            "spread": _spread_deltas(conn),
        }


def get_what_changed(max_events: int = 8) -> list[dict]:
    """Lista zdarzeń: {severity, icon, title, detail}. Sort: severity desc, |impact| desc."""
    d = get_market_deltas()
    events = []

    def add(severity, title, detail, impact=0.0):
        icon = {3: "🔴", 2: "🟠", 1: "🟢", 0: "⚪"}[severity]
        events.append({"severity": severity, "icon": icon,
                       "title": title, "detail": detail, "impact": abs(impact)})

    o, r, t, s = d["office"], d["residential"], d["transactions"], d["spread"]

    # Transakcje
    if t["volume_chg"] is not None and t["tx_prev"] >= 3:
        v = t["volume_chg"]
        if v <= -15:
            add(3, f"Wolumen transakcji spadł o {abs(v):.0f}%",
                f"{t['tx_30']} transakcji w 30 dni vs {t['tx_prev']} poprzednio", v)
        elif v >= 15:
            add(1, f"Wolumen transakcji wzrósł o {v:.0f}%",
                f"{t['tx_30']} transakcji w 30 dni vs {t['tx_prev']} poprzednio", v)
    if t["price_chg"] is not None and abs(t["price_chg"]) >= 2:
        sev = 2 if t["price_chg"] < 0 else 1
        add(sev, f"Ceny transakcyjne {'spadły' if t['price_chg']<0 else 'wzrosły'} o {abs(t['price_chg']):.1f}%",
            "median 90d vs poprzednie 90d", t["price_chg"])

    # Spread
    if s["spread_chg"] is not None and abs(s["spread_chg"]) >= 1:
        if s["spread_chg"] < 0:
            add(2, f"Spread pogłębił się o {abs(s['spread_chg']):.1f} pkt%",
                f"obecnie {s['spread_now']:.1f}% — rosnące pole negocjacji kupujących", s["spread_chg"])
        else:
            add(1, f"Spread zawęża się o {s['spread_chg']:.1f} pkt%",
                f"obecnie {s['spread_now']:.1f}% — oferty bliżej cen transakcyjnych", s["spread_chg"])

    # Office
    if o["rent_chg"] is not None and abs(o["rent_chg"]) >= 2:
        sev = 2 if o["rent_chg"] < -5 else (1 if o["rent_chg"] > 0 else 0)
        add(sev, f"Czynsze biurowe {'spadły' if o['rent_chg']<0 else 'wzrosły'} o {abs(o['rent_chg']):.1f}%",
            "okno 14d vs 30d wcześniej", o["rent_chg"])
    if o["supply_chg"] is not None and abs(o["supply_chg"]) >= 10:
        if o["supply_chg"] < 0:
            add(1, f"Nowa podaż biur niższa o {abs(o['supply_chg']):.0f}%",
                f"{o['new_30']} nowych ofert (30d) — mniejsza presja konkurencyjna na Ocean Plaza", o["supply_chg"])
        else:
            add(2, f"Nowa podaż biur wyższa o {o['supply_chg']:.0f}%",
                f"{o['new_30']} nowych ofert (30d) — rosnąca konkurencja", o["supply_chg"])

    # Residential
    if r["velocity_chg"] is not None and abs(r["velocity_chg"]) >= 10:
        sev = 1 if r["velocity_chg"] > 0 else 2
        add(sev, f"Tempo sprzedaży mieszkań {'rośnie' if r['velocity_chg']>0 else 'spada'} ({r['velocity_chg']:+.0f}%)",
            f"{r['sold_30']} zdjętych ofert w 30 dni", r["velocity_chg"])
    if r["price_chg"] is not None and abs(r["price_chg"]) >= 1.5:
        add(0, f"Ceny ofertowe mieszkań {'+' if r['price_chg']>0 else ''}{r['price_chg']:.1f}%",
            "okno 14d vs 30d wcześniej", r["price_chg"])

    events.sort(key=lambda e: (-e["severity"], -e["impact"]))
    return events[:max_events]


def generate_market_narrative() -> str:
    """Zwięzły akapit — każde zdanie ma pokrycie w metrykach; brak danych = brak zdania."""
    d = get_market_deltas()
    o, r, t, s = d["office"], d["residential"], d["transactions"], d["spread"]
    parts = []

    if t["volume_chg"] is not None and t["tx_prev"] >= 3:
        kier = "wzrosła" if t["volume_chg"] > 0 else "spadła"
        parts.append(f"Aktywność transakcyjna na Mokotowie {kier} o {abs(t['volume_chg']):.0f}% "
                     f"w ostatnich 30 dniach ({t['tx_30']} vs {t['tx_prev']} transakcji).")
    elif t["tx_30"]:
        parts.append(f"W ostatnich 30 dniach zarejestrowano {t['tx_30']} transakcji na Mokotowie.")

    if t["price_chg"] is not None and r["price_chg"] is not None:
        tx_desc = ("pozostały stabilne" if abs(t["price_chg"]) < 1.5
                   else f"{'wzrosły' if t['price_chg']>0 else 'spadły'} o {abs(t['price_chg']):.1f}%")
        ask_desc = ("pozostały stabilne" if abs(r["price_chg"]) < 1
                    else f"{'wzrosły' if r['price_chg']>0 else 'spadły'} o {abs(r['price_chg']):.1f}%")
        parts.append(f"Mediany cen transakcyjnych {tx_desc}, a ceny ofertowe {ask_desc}.")

    if s["spread_now"] is not None:
        if s["spread_chg"] is not None and abs(s["spread_chg"]) >= 0.5:
            kier = "pogłębiając" if s["spread_chg"] < 0 else "zawężając"
            parts.append(f"Luka cenowa między rynkiem ofertowym a transakcyjnym wynosi "
                         f"{s['spread_now']:.1f}%, {kier} się o {abs(s['spread_chg']):.1f} pkt%.")
        else:
            parts.append(f"Luka cenowa między rynkiem ofertowym a transakcyjnym utrzymuje się "
                         f"na poziomie {s['spread_now']:.1f}%.")

    if o["supply_chg"] is not None and abs(o["supply_chg"]) >= 10:
        if o["supply_chg"] < 0:
            parts.append(f"Nowa podaż biurowa w otoczeniu Ocean Plaza zmalała o "
                         f"{abs(o['supply_chg']):.0f}%, co wzmacnia pozycję konkurencyjną aktywa.")
        else:
            parts.append(f"Nowa podaż biurowa wzrosła o {o['supply_chg']:.0f}% — "
                         f"rośnie presja konkurencyjna na czynsze.")
    elif o["rent_chg"] is not None and abs(o["rent_chg"]) >= 2:
        parts.append(f"Czynsze ofertowe biur {'rosną' if o['rent_chg']>0 else 'spadają'} "
                     f"({o['rent_chg']:+.1f}% w ujęciu 14-dniowym).")

    return " ".join(parts) if parts else \
        "Za mało danych do wygenerowania podsumowania — uruchom scrapery i collectory."


def generate_market_brief() -> str:
    """Pełny Market Brief w Markdown (eksportowalny). Struktura: Executive Summary,
    Office, Residential, Transactions, Risks, Opportunities."""
    from .health import compute_office_health_score, compute_residential_health_score
    from .pricing import (get_pricing_kpis, compute_liquidity_score,
                          compute_pricing_pressure_score)
    from .listings import get_office_kpis_with_deltas, get_residential_kpis_with_deltas
    from .transactions import get_transaction_kpis

    d = get_market_deltas()
    oh = compute_office_health_score()
    rh = compute_residential_health_score()
    pk = get_pricing_kpis("residential", window_days=90)
    liq = compute_liquidity_score("residential")
    pp = compute_pricing_pressure_score("residential")
    ok = get_office_kpis_with_deltas()
    rk = get_residential_kpis_with_deltas()
    tk = get_transaction_kpis("residential", window_days=90)
    events = get_what_changed()
    narrative = generate_market_narrative()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def fmt(v, suffix=""):
        return f"{v:,.0f}{suffix}".replace(",", " ") if v is not None else "n/d"

    lines = [
        f"# Ocean Plaza — Market Brief",
        f"*Wygenerowano: {ts} · dane: Otodom (oferty), NBP BaRN + import (transakcje)*",
        "",
        "## Executive Summary",
        "",
        narrative,
        "",
        "**Kluczowe zdarzenia:**",
        "",
    ]
    for e in events[:5]:
        lines.append(f"- {e['icon']} {e['title']} — {e['detail']}")
    lines += [
        "",
        "## Office Market",
        "",
        f"- Market Health: **{oh['score']}/100 ({oh['label']})**",
        f"- Średni czynsz: **{fmt(ok['avg_rent']['value'], ' PLN/m²/mc')}**"
        + (f" ({ok['avg_rent']['delta']:+.1f}% m/m)" if ok['avg_rent']['delta'] is not None else ""),
        f"- Aktywne oferty: **{fmt(ok['active_count']['value'])}**",
        f"- Nowa podaż 30d: {fmt(ok['new_30d']['value'])} · Absorpcja 30d: {fmt(ok['absorbed_30d']['value'])}",
        "",
        "## Residential Market",
        "",
        f"- Market Health: **{rh['score']}/100 ({rh['label']})**",
        f"- Średnia cena ofertowa: **{fmt(rk['median_price_m2']['value'], ' PLN/m²')}**"
        + (f" ({rk['median_price_m2']['delta']:+.1f}% m/m)" if rk['median_price_m2']['delta'] is not None else ""),
        f"- Aktywne oferty: **{fmt(rk['active_listings']['value'])}**",
        "",
        "## Transaction Market",
        "",
        f"- Transakcje (90d): **{tk['transaction_count']}** · mediana **{fmt(tk['median_price_per_m2'], ' PLN/m²')}**",
        f"- Spread asking↔transaction: **{pk['spread_pct'] if pk['spread_pct'] is not None else 'n/d'}%** "
        f"(ufność: {pk['confidence']})",
        f"- Liquidity Score: **{liq['score'] if liq['score'] is not None else 'n/d'}"
        + (f"/100 ({liq['label']})**" if liq['score'] is not None else "**"),
        f"- Pricing Pressure: **{pp['score']}/100 ({pp['label']})**",
    ]
    if pk.get("nbp_benchmark"):
        nb = pk["nbp_benchmark"]
        lines.append(f"- Benchmark NBP (Warszawa): transakcje {fmt(nb['transaction'], ' PLN/m²')} "
                     f"vs asking Mokotów {fmt(nb['asking'], ' PLN/m²')} → {nb['spread_pct']}%")

    risks = [e for e in events if e["severity"] >= 2]
    opps = [e for e in events if e["severity"] == 1]
    lines += ["", "## Risks", ""]
    lines += [f"- {e['title']} — {e['detail']}" for e in risks] or ["- Brak istotnych sygnałów ryzyka w bieżących danych."]
    lines += ["", "## Opportunities", ""]
    lines += [f"- {e['title']} — {e['detail']}" for e in opps] or ["- Brak wyraźnych sygnałów sprzyjających w bieżących danych."]
    lines += ["", "---", "*Raport wygenerowany deterministycznie z metryk platformy — bez użycia LLM.*"]
    return "\n".join(lines)


def generate_market_brief_pdf() -> bytes:
    """Renderuje Market Brief (ten sam content co markdown) do PDF przez reportlab.
    Zwraca bytes — gotowe do st.download_button. Zero zewnętrznych zależności systemowych."""
    import re
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, HRFlowable)

    md = generate_market_brief()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=18*mm, bottomMargin=18*mm,
                            leftMargin=18*mm, rightMargin=18*mm,
                            title="Ocean Plaza — Market Brief")

    styles = getSampleStyleSheet()
    GOLD = colors.HexColor("#9a7d2e")
    DARK = colors.HexColor("#1a1d26")
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=20, textColor=GOLD,
                        spaceAfter=4, spaceBefore=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, textColor=DARK,
                        spaceBefore=12, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=15,
                          spaceAfter=3)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2)
    meta = ParagraphStyle("meta", parent=body, fontSize=8,
                          textColor=colors.HexColor("#666666"))

    def md_inline(t: str) -> str:
        # **bold** → <b>, *italic* → <i>, usuń znaki które łamią reportlab
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
        return t

    flow = []
    for raw in md.split("\n"):
        line = raw.rstrip()
        if not line:
            flow.append(Spacer(1, 4))
        elif line.startswith("# "):
            flow.append(Paragraph(md_inline(line[2:]), h1))
        elif line.startswith("## "):
            flow.append(Paragraph(md_inline(line[3:]), h2))
        elif line.startswith("- "):
            flow.append(Paragraph(md_inline(line[2:]), bullet, bulletText="•"))
        elif line.startswith("*") and line.endswith("*") and len(line) > 2:
            flow.append(Paragraph(md_inline(line), meta))
        elif line.startswith("---"):
            flow.append(Spacer(1, 4))
            flow.append(HRFlowable(width="100%", thickness=0.5,
                                   color=colors.HexColor("#cccccc")))
        else:
            flow.append(Paragraph(md_inline(line), body))

    doc.build(flow)
    buf.seek(0)
    return buf.getvalue()
