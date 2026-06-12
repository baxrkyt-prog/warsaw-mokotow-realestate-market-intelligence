"""
scraper_office.py — Playwright scraper Otodom, biura Mokotów.

Użycie:
    python scraper_office.py
"""

import argparse
import logging
import random
import re
import time
from datetime import datetime, timezone

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
log = logging.getLogger("scraper_office")

# Lokale komercyjne Mokotów — /lokal/ bo większość biur jest tam, nie w /biuro/
# Filtrowanie na poziomie parse_listing: min powierzchnia, odrzucenie restauracji itp.
DEFAULT_URL = (
    "https://www.otodom.pl/pl/wyniki/wynajem/lokal/mazowieckie/warszawa"
    "/warszawa/warszawa/mokotow?limit=36&ownerTypeSingleSelect=ALL"
    "&by=DEFAULT&direction=DESC"
)

# Dodatkowo scrapuj stricte biura (mniej wyników, ale bardziej precyzyjne)
OFFICE_ONLY_URL = (
    "https://www.otodom.pl/pl/wyniki/wynajem/biuro/mazowieckie/warszawa"
    "/warszawa/warszawa/mokotow?limit=36&ownerTypeSingleSelect=ALL"
    "&by=DEFAULT&direction=DESC"
)

DELAY_MIN = 2.5
DELAY_MAX = 5.5
PAGE_LOAD_TIMEOUT = 60_000

LISTING_SELECTOR = "[data-cy='search.listing.organic'] article"
NEXT_PAGE_SELECTOR = "a[data-cy='pagination.next-page']"

# Znane budynki biurowe w okolicy Ocean Plaza (Służewiec)
KNOWN_BUILDINGS = {
    "ocean plaza": "Ocean Plaza",
    "ocean business": "Ocean Business Park",
    "curtis plaza": "Curtis Plaza",
    "new city": "New City",
    "marynarska": "Marynarska Business Park",
    "eurocentrum": "Eurocentrum",
    "platinium": "Platinium Business Park",
    "adgar": "Adgar Park West",
    "astrum": "Astrum Business Park",
    "park postępu": "Park Postępu",
    "nimbus": "Nimbus Office Building",
    "konstruktorska": "Konstruktorska Business Center",
}


def detect_building(text):
    text_lower = text.lower()
    for key, name in KNOWN_BUILDINGS.items():
        if key in text_lower:
            return name
    return None


def detect_building_class(text):
    m = re.search(r"klas[ay]\s+([ABC][+]?)", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    text_lower = text.lower()
    if "klasa a" in text_lower or "class a" in text_lower:
        return "A"
    if "klasa b+" in text_lower or "b+" in text_lower:
        return "B+"
    if "klasa b" in text_lower:
        return "B"
    return None


def parse_price(text):
    """Wyciąga pierwszą liczbę z tekstu ceny (ignoruje kolejne linie)."""
    if not text:
        return None
    first_line = text.replace("\xa0", " ").strip().split("\n")[0]
    is_eur = "€" in first_line or "eur" in first_line.lower()
    m = re.search(r"([\d\s]+)\s*(?:zł|€|eur|pln)", first_line, re.IGNORECASE)
    if m:
        digits = re.sub(r"\s", "", m.group(1))
        try:
            val = float(digits)
            if is_eur:
                val = round(val * 4.25, 2)
            return val
        except ValueError:
            return None
    m2 = re.search(r"(\d[\d\s]{1,12}\d|\d+)", first_line)
    if m2:
        digits = re.sub(r"\s", "", m2.group(1))
        try:
            val = float(digits)
            if is_eur:
                val = round(val * 4.25, 2)
            return val
        except ValueError:
            return None
    return None


def parse_listing(article):
    try:
        link_el = article.query_selector("a[href*='/oferta/']")
        if not link_el:
            return None
        href = link_el.get_attribute("href") or ""
        url = ("https://www.otodom.pl" + href if href.startswith("/") else href).split("?")[0]

        # Odrzuć sponsorowane mieszkania wstrzykiwane w wyniki
        if re.search(r"/(mieszkanie|apartament|dom-|kawalerka|pokoj|dzialka)-", url, re.IGNORECASE):
            return None

        offer_id = extract_otodom_id(url)

        title_el = article.query_selector("[data-cy='listing-item-title']")
        title = title_el.inner_text().strip() if title_el else ""

        price_el = article.query_selector("[data-cy='listing-item-price']")
        price_text = price_el.inner_text().strip() if price_el else None
        price_total = parse_price(price_text)
        price_per_m2 = None

        full_text = article.inner_text()

        area_m = re.search(r"([\d\s,]+)\s*m²", full_text)
        area_m2 = None
        if area_m:
            try:
                area_m2 = float(area_m.group(1).replace("\xa0", "").replace(" ", "").replace(",", "."))
            except ValueError:
                pass

        # Cena za m²/miesiąc dla najmu biur
        if area_m2 and area_m2 > 0 and price_total and not price_per_m2:
            price_per_m2 = round(price_total / area_m2, 2)

        combined = (title + " " + full_text).lower()

        # Odrzuć mieszkania
        if re.search(r"\d+\s*poko[ij]|kawalerka|mieszkanie\b|apartament\b", combined):
            return None

        # Odrzuć gastronomię i usługi niebiurowe
        if re.search(
            r"restauracj|gastronomicz|kebab|pizz|cateringow|kuchni[a-z]|"
            r"salon piękności|fryzjer|kosmetyczn|gabinet lekarski|stomatolog|"
            r"sklep\b|handlow|magazyn|hala\b|warsztat|serwis",
            combined
        ):
            return None

        # Minimalna powierzchnia biurowa
        if area_m2 and area_m2 < 20:
            return None

        # Odrzuć jeśli cena/m² poniżej 20 PLN (mieszkania wynajmowane jako biuro)
        if price_per_m2 and price_per_m2 < 20:
            return None

        building_name = detect_building(title + " " + full_text)
        building_class = detect_building_class(full_text)

        advertiser = "agency"
        if re.search(r"deweloper|developer", full_text, re.IGNORECASE):
            advertiser = "developer"
        elif re.search(r"właściciel|prywatny", full_text, re.IGNORECASE):
            advertiser = "private"

        return {
            "offer_id":         offer_id,
            "source":           "otodom",
            "asset_class":      "office",
            "transaction_type": "rent",
            "title":            title,
            "url":              url,
            "district":         "Mokotów",
            "subdistrict":      "służewiec",
            "address":          None,
            "area_m2":          area_m2,
            "rooms":            None,
            "floor":            None,
            "building_name":    building_name,
            "building_class":   building_class,
            "price_total":      price_total,
            "price_per_m2":      price_per_m2,
            "currency":          "PLN",
            "advertiser_type":   advertiser,
            "parent_project_id": None,
        }

    except Exception as e:
        log.warning(f"[PARSE ERROR] {e}")
        return None


def scrape(url: str, headless: bool = True) -> list:
    all_offers = []

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

        for page_num in range(1, 20):
            current_url = base_url if page_num == 1 else f"{base_url}{sep}page={page_num}"
            log.info(f"[SCRAPE] Strona {page_num}: {current_url[:90]}...")
            try:
                page.goto(current_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                page.wait_for_timeout(4000)
            except PWTimeout:
                log.warning(f"[TIMEOUT] Strona {page_num}")
                break
            except Exception as e:
                log.error(f"[NAV ERROR] {e}")
                break

            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

            articles = page.query_selector_all(LISTING_SELECTOR)
            log.info(f"  → {len(articles)} ogłoszeń")

            if not articles:
                log.info("  → brak wyników, koniec paginacji")
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

    log.info(f"[SCRAPE] Łącznie: {len(all_offers)} ofert biurowych")
    return all_offers


def save_to_db(offers: list, source_url: str) -> dict:
    now = datetime.now(timezone.utc)
    scrape_ts = now.isoformat()
    scrape_date = now.date().isoformat()

    stats = {
        "run_ts": scrape_ts,
        "source": "otodom",
        "asset_class": "office",
        "url_scraped": source_url,
        "offers_found": len(offers),
        "new_listings": 0,
        "delisted": 0,
        "price_changes": 0,
        "status": "ok",
        "error_msg": None,
    }

    with get_conn() as conn:
        prev_active = get_last_active_offer_ids(conn, "office")
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
        coverage = len(current_ids) / max(len(prev_active), 1)
        if disappeared and coverage >= 0.85:
            mark_delisted(conn, list(disappeared), scrape_date, scrape_ts)
            stats["delisted"] = len(disappeared)
        elif disappeared:
            log.warning(f"[SKIP DELIST] coverage={coverage:.0%} < 85% — pomijam {len(disappeared)} delist")

        log_run(conn, stats)

    log.info(
        f"[DB] nowe={stats['new_listings']}, delisted={stats['delisted']}, "
        f"zmiany cen={stats['price_changes']}"
    )
    return stats


def main():
    parser = argparse.ArgumentParser(description="Otodom Office Scraper — Mokotów")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--init-only", action="store_true")
    parser.add_argument("--show-browser", action="store_true", help="Pokaż okno przeglądarki")
    args = parser.parse_args()

    init_db()
    if args.init_only:
        return

    urls_to_scrape = [args.url]
    # Jeśli używamy domyślnego URL, dorzuć też /biuro/
    if args.url == DEFAULT_URL:
        urls_to_scrape.append(OFFICE_ONLY_URL)

    all_offers = []
    seen = set()
    for u in urls_to_scrape:
        log.info(f"[START] Scrapowanie: {u[:80]}...")
        try:
            batch = scrape(u, headless=not args.show_browser)
            for o in batch:
                if o["offer_id"] not in seen:
                    seen.add(o["offer_id"])
                    all_offers.append(o)
            log.info(f"  → {len(batch)} ofert z tego URL-a")
        except Exception as e:
            log.error(f"[ERROR] {u}: {e}")

    offers = all_offers
    if offers:
        save_to_db(offers, args.url)
    else:
        log.warning("[WARN] Brak ofert — sprawdź selektor lub połączenie")


if __name__ == "__main__":
    main()
