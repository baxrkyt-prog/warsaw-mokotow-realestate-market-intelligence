"""
scraper_morizon.py — Morizon (drugie źródło ofert obok Otodom).
Mieszkania na sprzedaż, Mokotów. source='morizon', asset_class='residential', sale.

Delisting scope'owany per source — nie dotyka ofert Otodom.
Generuje eventy lifecycle (CREATED/PRICE_*/DELISTED/RELISTED) jak Otodom.
"""

import re
import time
import random
import logging
import argparse
from datetime import datetime, timezone
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from database import (
    init_db, get_conn, upsert_listing, insert_snapshot, mark_delisted,
    get_last_active_offer_ids, log_run, insert_lifecycle_event,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("morizon")

SALE_URL = "https://www.morizon.pl/mieszkania/warszawa/mokotow/"
PAGE_LOAD_TIMEOUT = 60_000
DELAY_MIN, DELAY_MAX = 2.0, 4.0
CARD_SELECTOR = "div.card"

SUBDISTRICTS = ["służewiec", "ksawerów", "wyględów", "stegny", "sadyba",
                "stary mokotów", "górny mokotów", "wierzbno", "siekierki",
                "służew", "czerniaków", "mokotów"]


def parse_price(text) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"([\d\s ]+)", text.replace("\xa0", " "))
    if not m:
        return None
    try:
        return float(m.group(1).replace(" ", ""))
    except ValueError:
        return None


def detect_subdistrict(text: str) -> Optional[str]:
    t = (text or "").lower()
    for s in SUBDISTRICTS:
        if s in t:
            return s
    return None


def parse_card(card) -> Optional[dict]:
    try:
        link = card.query_selector("a[href*='/oferta/']")
        if not link:
            return None
        href = link.get_attribute("href") or ""
        url = ("https://www.morizon.pl" + href if href.startswith("/") else href).split("?")[0]
        m = re.search(r"-(mzn\d+)$", url)
        if not m:
            return None
        offer_id = m.group(1)

        txt = card.inner_text()
        # cena całkowita i za m²
        price_total = None
        pm = re.search(r"([\d\s ]+)\s*zł(?!/)", txt.replace("\xa0", " "))
        if pm:
            price_total = parse_price(pm.group(1))
        price_per_m2 = None
        pm2 = re.search(r"([\d\s ]+)\s*zł/m", txt.replace("\xa0", " "))
        if pm2:
            price_per_m2 = parse_price(pm2.group(1))

        area_m2 = None
        am = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", txt)
        if am:
            area_m2 = float(am.group(1).replace(",", "."))

        rooms = None
        rm = re.search(r"(\d+)\s*pok", txt, re.IGNORECASE)
        if rm:
            rooms = int(rm.group(1))

        floor = None
        fm = re.search(r"piętro\s*(\d+)", txt, re.IGNORECASE)
        if fm:
            floor = fm.group(1)

        if area_m2 and price_total and not price_per_m2:
            price_per_m2 = round(price_total / area_m2, 2)

        title = txt.split("\n")[1].strip() if "\n" in txt else txt[:60]

        return {
            "offer_id": offer_id, "source": "morizon", "asset_class": "residential",
            "transaction_type": "sale", "title": title[:200], "url": url,
            "district": "Mokotów", "subdistrict": detect_subdistrict(txt),
            "address": None, "area_m2": area_m2, "rooms": rooms, "floor": floor,
            "building_name": None, "building_class": None,
            "price_total": price_total, "price_per_m2": price_per_m2,
            "currency": "PLN", "advertiser_type": "unknown",
            "parent_project_id": None, "published_date": None,
        }
    except Exception as e:
        log.warning(f"[PARSE ERROR] {e}")
        return None


def scrape(url: str, headless: bool = True) -> tuple:
    all_offers = []
    nav_error = False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}, locale="pl-PL",
        ).new_page()

        seen = set()
        for page_num in range(1, 30):
            current = url if page_num == 1 else f"{url}?page={page_num}"
            log.info(f"[SCRAPE] Strona {page_num}")
            try:
                page.goto(current, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                page.wait_for_timeout(3500)
            except PWTimeout:
                log.warning(f"[TIMEOUT] Strona {page_num}"); nav_error = True; break
            except Exception as e:
                log.error(f"[NAV ERROR] {e}"); nav_error = True; break

            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            cards = page.query_selector_all(CARD_SELECTOR)
            new_on_page = 0
            for c in cards:
                o = parse_card(c)
                if o and o["offer_id"] not in seen and o["price_total"]:
                    seen.add(o["offer_id"])
                    all_offers.append(o)
                    new_on_page += 1
            log.info(f"  → {new_on_page} ofert")
            if new_on_page == 0:
                break

        browser.close()
    log.info(f"[SCRAPE] Łącznie: {len(all_offers)} ofert Morizon")
    return all_offers, nav_error


def save_to_db(offers: list, source_url: str, nav_error: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    scrape_ts = now.isoformat()
    scrape_date = now.date().isoformat()
    run_status = "error" if not offers else ("partial" if nav_error else "ok")

    stats = {"run_ts": scrape_ts, "source": "morizon", "asset_class": "residential",
             "url_scraped": source_url, "offers_found": len(offers), "new_listings": 0,
             "delisted": 0, "price_changes": 0, "status": run_status,
             "error_msg": "navigation interrupted" if nav_error else None}

    with get_conn() as conn:
        prev_active = get_last_active_offer_ids(conn, "residential", "sale", source="morizon")
        current_ids = set()
        for offer in offers:
            oid = offer["offer_id"]
            current_ids.add(oid)
            existing = conn.execute(
                "SELECT price_total, is_active FROM listings WHERE offer_id = ?", (oid,)).fetchone()
            new_price = offer["price_total"]
            new_status = "ACTIVE"
            if not existing:
                stats["new_listings"] += 1
                insert_lifecycle_event(conn, oid, scrape_date, "LISTING_CREATED", None, new_price)
            else:
                if existing["is_active"] == 0:
                    insert_lifecycle_event(conn, oid, scrape_date, "RELISTED", None, new_price)
                if existing["price_total"] and new_price and abs(existing["price_total"] - new_price) > 1:
                    stats["price_changes"] += 1
                    if new_price < existing["price_total"]:
                        new_status = "PRICE_REDUCED"
                        insert_lifecycle_event(conn, oid, scrape_date, "PRICE_REDUCED", existing["price_total"], new_price)
                    else:
                        new_status = "PRICE_INCREASED"
                        insert_lifecycle_event(conn, oid, scrape_date, "PRICE_INCREASED", existing["price_total"], new_price)

            upsert_listing(conn, {**offer, "first_seen": scrape_ts, "last_seen": scrape_ts})
            insert_snapshot(conn, {"offer_id": oid, "scrape_date": scrape_date, "scrape_ts": scrape_ts,
                                   "active_status": 1, "current_price": new_price,
                                   "current_price_m2": offer["price_per_m2"]})
            conn.execute("""
                UPDATE listings SET listing_status=?, last_known_price=?,
                    last_known_price_per_m2=?, delisted_date=NULL WHERE offer_id=?
            """, (new_status, new_price, offer["price_per_m2"], oid))

        disappeared = prev_active - current_ids
        coverage = len(current_ids) / max(len(prev_active), 1)
        if disappeared and run_status == "ok" and coverage >= 0.85:
            mark_delisted(conn, list(disappeared), scrape_date, scrape_ts)
            stats["delisted"] = len(disappeared)
        elif disappeared:
            log.warning(f"[SKIP DELIST] status={run_status} coverage={coverage:.0%}")

        log_run(conn, stats)
    log.info(f"[DB] nowe={stats['new_listings']}, delisted={stats['delisted']}, Δceny={stats['price_changes']}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Morizon Scraper — Mokotów")
    parser.add_argument("--show-browser", action="store_true")
    args = parser.parse_args()
    init_db()
    log.info("[START] Scrapowanie Morizon mieszkania Mokotów")
    try:
        offers, nav_error = scrape(SALE_URL, headless=not args.show_browser)
        save_to_db(offers, SALE_URL, nav_error=nav_error)
        if not offers:
            log.warning("[WARN] Brak ofert — run zapisany jako status=error")
    except Exception as e:
        log.error(f"[FATAL] {e}", exc_info=True)


if __name__ == "__main__":
    main()
