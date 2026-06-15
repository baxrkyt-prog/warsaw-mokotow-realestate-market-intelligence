"""
scraper_residential.py — Playwright scraper Otodom, sprzedaż mieszkań Mokotów.

Użycie:
    python scraper_residential.py
"""

import argparse
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from database import (
    init_db, get_conn, extract_otodom_id,
    upsert_listing, insert_snapshot, mark_delisted,
    get_last_active_offer_ids, log_run
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("scraper_residential")

SALE_URL = (
    "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/mazowieckie/warszawa"
    "/warszawa/warszawa/mokotow?limit=36&ownerTypeSingleSelect=ALL"
    "&by=DEFAULT&direction=DESC"
)

DELAY_MIN = 2.5
DELAY_MAX = 5.5
PAGE_LOAD_TIMEOUT = 60_000
LISTING_SELECTOR = "[data-cy='search.listing.organic'] article"

MOKOTOW_SUBDISTRICTS = {
    "służewiec": ["służewiec", "domaniewska", "wołoska", "postępu"],
    "ksawerów":  ["ksawerów", "ksawerow"],
    "sadyba":    ["sadyba", "powsińska"],
    "stary mokotów": ["puławska", "różana", "malczewskiego", "kazimierzowska"],
    "siekierki": ["siekierki", "czerniakowska"],
    "wierzbno":  ["wierzbno", "niepodległości"],
    "górny mokotów": ["rakowiecka", "górny mokotów"],
}


def detect_subdistrict(text: str) -> str:
    tl = text.lower()
    for sub, keywords in MOKOTOW_SUBDISTRICTS.items():
        for kw in keywords:
            if kw in tl:
                return sub
    return "mokotów"


def parse_price(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    first_line = text.replace("\xa0", " ").strip().split("\n")[0]
    m = re.search(r"([\d\s]+)\s*(?:zł|€|eur|pln)", first_line, re.IGNORECASE)
    if m:
        digits = re.sub(r"\s", "", m.group(1))
        try:
            return float(digits)
        except ValueError:
            return None
    m2 = re.search(r"(\d[\d\s]{1,12}\d|\d+)", first_line)
    if m2:
        digits = re.sub(r"\s", "", m2.group(1))
        try:
            return float(digits)
        except ValueError:
            return None
    return None


def parse_listing(article) -> Optional[dict]:
    try:
        link_el = article.query_selector("a[href*='/oferta/']")
        if not link_el:
            return None
        href = link_el.get_attribute("href") or ""
        url = ("https://www.otodom.pl" + href if href.startswith("/") else href).split("?")[0]
        offer_id = extract_otodom_id(url)

        title_el = article.query_selector("[data-cy='listing-item-title']")
        title = title_el.inner_text().strip() if title_el else ""

        price_el = article.query_selector("[data-cy='listing-item-price']")
        price_text = price_el.inner_text().strip() if price_el else None
        price_total = parse_price(price_text)

        price_per_m2 = None
        if price_text:
            m2_m = re.search(r"([\d\s]+)\s*zł/m²", price_text.replace("\xa0", " "))
            if m2_m:
                price_per_m2 = parse_price(m2_m.group(1))

        full_text = article.inner_text()

        area_m = re.search(r"([\d,]+)\s*m²", full_text)
        area_m2 = float(area_m.group(1).replace(",", ".")) if area_m else None

        rooms_m = re.search(r"(\d+)\s*poko[ij]", full_text, re.IGNORECASE)
        rooms = int(rooms_m.group(1)) if rooms_m else None

        floor_m = re.search(r"Piętro\s*(\d+|parter)", full_text, re.IGNORECASE)
        floor = floor_m.group(1) if floor_m else None

        # cena/m² z powierzchni jeśli brak
        if area_m2 and price_total and not price_per_m2:
            price_per_m2 = round(price_total / area_m2, 2)

        advertiser = "unknown"
        if re.search(r"deweloper", full_text, re.IGNORECASE):
            advertiser = "developer"
        elif re.search(r"agencja|biuro nieruchomości", full_text, re.IGNORECASE):
            advertiser = "agency"
        elif re.search(r"prywatny|właściciel", full_text, re.IGNORECASE):
            advertiser = "private"

        subdistrict = detect_subdistrict(title + " " + full_text)

        return {
            "offer_id":          offer_id,
            "source":            "otodom",
            "asset_class":       "residential",
            "transaction_type":  "sale",
            "title":             title,
            "url":               url,
            "district":          "Mokotów",
            "subdistrict":       subdistrict,
            "address":           None,
            "area_m2":           area_m2,
            "rooms":             rooms,
            "floor":             floor,
            "building_name":     None,
            "building_class":    None,
            "price_total":       price_total,
            "price_per_m2":      price_per_m2,
            "currency":          "PLN",
            "advertiser_type":   advertiser,
            "parent_project_id": None,
        }

    except Exception as e:
        log.warning(f"[PARSE ERROR] {e}")
        return None


def scrape(url: str, headless: bool = True) -> tuple:
    """Zwraca (offers, nav_error) — nav_error=True gdy nawigacja padła
    (timeout/błąd sieci) i scrape jest niekompletny."""
    all_offers = []
    nav_error = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="pl-PL",
            extra_http_headers={
                "Accept-Language": "pl-PL,pl;q=0.9",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            }
        )
        page = context.new_page()
        base_url = url.split("&page=")[0].split("?page=")[0]
        sep = "&" if "?" in base_url else "?"
        seen_ids = set()

        for page_num in range(1, 30):
            current_url = base_url if page_num == 1 else f"{base_url}{sep}page={page_num}"
            log.info(f"[SCRAPE] Strona {page_num}: {current_url[:90]}...")
            try:
                page.goto(current_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                page.wait_for_timeout(4000)
            except PWTimeout:
                log.warning(f"[TIMEOUT] Strona {page_num}")
                nav_error = True
                break
            except Exception as e:
                log.error(f"[NAV ERROR] {e}")
                nav_error = True
                break

            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            articles = page.query_selector_all(LISTING_SELECTOR)
            log.info(f"  → {len(articles)} ogłoszeń")

            if not articles:
                break

            new_on_page = 0
            for art in articles:
                offer = parse_listing(art)
                if offer and offer["offer_id"] not in seen_ids:
                    seen_ids.add(offer["offer_id"])
                    all_offers.append(offer)
                    new_on_page += 1

            if new_on_page == 0:
                log.info("  → brak nowych ofert, koniec paginacji")
                break

        browser.close()

    log.info(f"[SCRAPE] Łącznie: {len(all_offers)} ofert sprzedaży")
    return all_offers, nav_error


def save_to_db(offers: list, source_url: str, nav_error: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    scrape_ts = now.isoformat()
    scrape_date = now.date().isoformat()

    # Status odzwierciedla rzeczywistość — nie zapisujemy fałszywego "ok":
    #   error   = nic nie pobrano (awaria sieci/blokada)
    #   partial = pobrano część, ale nawigacja padła (niekompletne dane)
    #   ok      = pełny, czysty scrape
    if not offers:
        run_status = "error"
    elif nav_error:
        run_status = "partial"
    else:
        run_status = "ok"

    stats = {
        "run_ts": scrape_ts,
        "source": "otodom",
        "asset_class": "residential",
        "url_scraped": source_url,
        "offers_found": len(offers),
        "new_listings": 0,
        "delisted": 0,
        "price_changes": 0,
        "status": run_status,
        "error_msg": "navigation interrupted" if nav_error else None,
    }

    with get_conn() as conn:
        prev_active = get_last_active_offer_ids(conn, "residential", "sale")
        current_ids = set()

        for offer in offers:
            oid = offer["offer_id"]
            current_ids.add(oid)

            existing = conn.execute(
                "SELECT price_total FROM listings WHERE offer_id = ?", (oid,)
            ).fetchone()

            if not existing:
                stats["new_listings"] += 1
            elif existing["price_total"] and offer["price_total"]:
                if abs(existing["price_total"] - offer["price_total"]) > 1:
                    stats["price_changes"] += 1

            upsert_listing(conn, {**offer, "first_seen": scrape_ts, "last_seen": scrape_ts})
            insert_snapshot(conn, {
                "offer_id":         oid,
                "scrape_date":      scrape_date,
                "scrape_ts":        scrape_ts,
                "active_status":    1,
                "current_price":    offer["price_total"],
                "current_price_m2": offer["price_per_m2"],
            })

        disappeared = prev_active - current_ids
        # Oznacz jako delisted tylko jeśli scrape był kompletny (znaleźliśmy
        # co najmniej 85% poprzednich aktywnych) — chroni przed fałszywymi
        # delistingami gdy scraper nie przeszedł wszystkich stron Otodom.
        coverage = len(current_ids) / max(len(prev_active), 1)
        if disappeared and run_status == "ok" and coverage >= 0.85:
            mark_delisted(conn, list(disappeared), scrape_date, scrape_ts)
            stats["delisted"] = len(disappeared)
        elif disappeared:
            log.warning(f"[SKIP DELIST] status={run_status} coverage={coverage:.0%} — pomijam {len(disappeared)} delist")

        log_run(conn, stats)

    log.info(f"[DB] nowe={stats['new_listings']}, delisted={stats['delisted']}, Δceny={stats['price_changes']}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Otodom Sale Scraper — Mokotów")
    parser.add_argument("--init-only", action="store_true")
    parser.add_argument("--show-browser", action="store_true")
    args = parser.parse_args()

    init_db()
    if args.init_only:
        return

    log.info("[START] Scrapowanie sprzedaży mieszkań Mokotów")
    try:
        offers, nav_error = scrape(SALE_URL, headless=not args.show_browser)
        save_to_db(offers, SALE_URL, nav_error=nav_error)
        if not offers:
            log.warning("[WARN] Brak ofert — run zapisany jako status=error")
    except Exception as e:
        log.error(f"[FATAL] {e}", exc_info=True)


if __name__ == "__main__":
    main()
