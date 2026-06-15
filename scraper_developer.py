"""
scraper_developer.py — Playwright scraper inwestycji deweloperskich Mokotów.

Scrapuje listę inwestycji z Otodom, wchodzi w każdą inwestycję,
wyciąga dostępne jednostki z tabeli [data-cy='ad-page-desktop-units-list']
i zapisuje je jako transaction_type='invest_unit' z parent_project_id.

Użycie:
    python scraper_developer.py
"""

import hashlib
import logging
import random
import re
import time
from datetime import datetime, timezone
from statistics import median
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from database import (
    init_db, get_conn, extract_otodom_id,
    upsert_listing, insert_snapshot,
    upsert_developer_project, upsert_project_snapshot,
    log_run
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("scraper_developer")

INVEST_LIST_URL = (
    "https://www.otodom.pl/pl/wyniki/sprzedaz/inwestycja/mazowieckie/warszawa"
    "/warszawa/warszawa/mokotow?limit=36&ownerTypeSingleSelect=ALL"
    "&by=DEFAULT&direction=DESC"
)

DELAY_MIN = 3.0
DELAY_MAX = 6.0
DETAIL_DELAY = 5.0
PAGE_LOAD_TIMEOUT = 60_000
LIST_SELECTOR = "[data-cy='search.listing.organic'] article"
UNITS_TABLE = "[data-cy='ad-page-desktop-units-list'] tr"

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


def make_project_id(url: str) -> str:
    clean = url.split("?")[0].rstrip("/")
    m = re.search(r"-ID([a-zA-Z0-9]+)$", clean)
    if m:
        return "proj_" + m.group(1)
    return "proj_" + hashlib.md5(clean.encode()).hexdigest()[:12]


def parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    text = text.replace("\xa0", " ").replace(",", ".")
    m = re.search(r"([\d\s]+)\s*(?:zł|pln)", text, re.IGNORECASE)
    if m:
        digits = re.sub(r"\s", "", m.group(1))
        try:
            return float(digits)
        except ValueError:
            return None
    return None


def parse_area(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"([\d,]+)\s*m", text.replace("\xa0", " "))
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None
    return None


def parse_unit_row(row_text: str) -> Optional[dict]:
    """
    Parsuje wiersz tabeli jednostek.
    Format: "Apartament X | pokoje | metraż m² | piętro | cena zł"
    """
    # Usuń nadmiarowe białe znaki
    parts = [p.strip() for p in re.split(r"\t|\n", row_text) if p.strip()]

    if len(parts) < 3:
        return None

    # Pomiń wiersz nagłówkowy
    if any(h in parts[0].lower() for h in ["numer", "pokoje", "metraż", "piętro", "cena"]):
        return None

    unit_name = parts[0]

    # Szukaj metrażu (zawiera m²)
    area_m2 = None
    price_total = None
    rooms = None
    floor = None

    for part in parts[1:]:
        part_clean = part.replace("\xa0", " ").strip()

        # Cena — zawiera "zł"
        if "zł" in part_clean and price_total is None:
            price_total = parse_price(part_clean)

        # Metraż — zawiera "m²" lub "m2"
        elif ("m²" in part_clean or "m2" in part_clean.lower()) and area_m2 is None:
            area_m2 = parse_area(part_clean)

        # Piętro — zawiera "/" lub "parter"
        elif ("/" in part_clean or "parter" in part_clean.lower()) and floor is None:
            floor = part_clean

        # Pokoje — sama liczba 1-6
        elif re.match(r"^[1-6]$", part_clean) and rooms is None:
            try:
                rooms = int(part_clean)
            except ValueError:
                pass

    if not price_total and not area_m2:
        return None

    price_per_m2 = None
    if price_total and area_m2 and area_m2 > 0:
        price_per_m2 = round(price_total / area_m2, 2)

    return {
        "unit_name":   unit_name,
        "rooms":       rooms,
        "area_m2":     area_m2,
        "floor":       floor,
        "price_total": price_total,
        "price_per_m2": price_per_m2,
    }


def scrape_project_detail(page, project_url: str) -> dict:
    """
    Wchodzi na stronę projektu, wyciąga:
    - dewelopera (z sekcji 'O deweloperze' lub meta)
    - adres
    - jednostki z tabeli
    Zwraca dict: {"developer": str|None, "address": str|None, "units": list}
    """
    result = {"developer": None, "address": None, "units": []}
    try:
        page.goto(project_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        page.wait_for_timeout(int(DETAIL_DELAY * 1000))
    except PWTimeout:
        log.warning(f"[TIMEOUT] {project_url}")
        return result
    except Exception as e:
        log.error(f"[NAV ERROR] {project_url}: {e}")
        return result

    time.sleep(random.uniform(2.0, 4.0))

    # ── Deweloper ─────────────────────────────────────────────────────────
    # data-cy='seller-info' zawiera "Nazwa Dewelopera | Deweloper | Pokaż numer..."
    # Pierwsza część przed " | " to nazwa — potwierdzone debug sesją.
    seller_el = page.query_selector("[data-cy='seller-info']")
    if seller_el:
        txt = seller_el.inner_text().strip()
        # inner_text używa \n jako separatora między elementami
        parts = [p.strip() for p in txt.split("\n") if p.strip()]
        if parts and len(parts[0]) > 1:
            result["developer"] = parts[0][:100]
            log.info(f"    → Deweloper [seller-info]: {result['developer']}")

    # Fallback: seller-ads-container zawiera "Więcej ogłoszeń od Nazwa | ..."
    if not result["developer"]:
        ads_el = page.query_selector("[data-cy='seller-ads-container']")
        if ads_el:
            txt2 = ads_el.inner_text().strip()
            m = re.search(r"od\s+([^\|]{2,60})\s*\|", txt2)
            if m:
                result["developer"] = m.group(1).strip()[:100]
                log.info(f"    → Deweloper [seller-ads-container]: {result['developer']}")

    if not result["developer"]:
        log.info("    → Deweloper: nie znaleziono")

    # ── Adres ─────────────────────────────────────────────────────────────
    addr_selectors = [
        "[data-cy='advert-address']",
        "[data-testid='advert-address']",
        "[aria-label*='adres']",
        "[class*='address']",
        "address",
    ]
    for sel in addr_selectors:
        el = page.query_selector(sel)
        if el:
            txt = el.inner_text().strip().replace("\n", ", ")
            if txt and len(txt) > 3:
                result["address"] = txt[:200]
                break

    # ── Jednostki z tabeli ────────────────────────────────────────────────
    rows = page.query_selector_all(UNITS_TABLE)
    log.info(f"    → {len(rows)} wierszy w tabeli jednostek")

    for row in rows:
        try:
            row_text = row.inner_text()
            unit = parse_unit_row(row_text)
            if unit:
                result["units"].append(unit)
        except Exception as e:
            log.warning(f"    [ROW ERROR] {e}")

    return result


def scrape_invest_list(page) -> list:
    """Scrapuje listę projektów inwestycyjnych (paginacja)."""
    projects = []
    base_url = INVEST_LIST_URL.split("&page=")[0].split("?page=")[0]
    sep = "&" if "?" in base_url else "?"
    seen_ids = set()

    for page_num in range(1, 20):
        current_url = base_url if page_num == 1 else f"{base_url}{sep}page={page_num}"
        log.info(f"[LIST] Strona {page_num}: {current_url[:90]}...")

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
        articles = page.query_selector_all(LIST_SELECTOR)
        log.info(f"  → {len(articles)} projektów")

        if not articles:
            break

        new_on_page = 0
        for art in articles:
            try:
                link_el = art.query_selector("[data-cy='listing-item-link'], a[href*='/oferta/']")
                if not link_el:
                    continue
                href = link_el.get_attribute("href") or ""
                url = ("https://www.otodom.pl" + href if href.startswith("/") else href).split("?")[0]
                project_id = make_project_id(url)

                if project_id in seen_ids:
                    continue
                seen_ids.add(project_id)
                new_on_page += 1

                full_text = art.inner_text()
                title_el = art.query_selector("[data-cy='listing-item-title']")
                title = title_el.inner_text().strip() if title_el else full_text[:80]

                developer_m = re.search(r"(?:deweloper|developer)[:\s]+([^\n]+)", full_text, re.IGNORECASE)
                developer = developer_m.group(1).strip()[:80] if developer_m else None

                subdistrict = detect_subdistrict(title + " " + full_text)

                projects.append({
                    "project_id":  project_id,
                    "name":        title,
                    "url":         url,
                    "developer":   developer,
                    "subdistrict": subdistrict,
                    "address":     None,
                })
            except Exception as e:
                log.warning(f"[PARSE ERROR] {e}")

        if new_on_page == 0:
            log.info("  → brak nowych projektów, koniec paginacji")
            break

    log.info(f"[LIST] Znaleziono {len(projects)} projektów")
    return projects


def save_project(conn, project: dict, units: list, scrape_ts: str, scrape_date: str) -> dict:
    stats = {"new_units": 0, "price_changes": 0}

    upsert_developer_project(conn, {**project, "first_seen": scrape_ts, "last_seen": scrape_ts})

    prices_m2 = []
    prices_total = []

    for i, unit in enumerate(units):
        # Unikalny offer_id: projekt + numer jednostki
        raw_key = f"{project['project_id']}:{unit['unit_name']}"
        offer_id = hashlib.md5(raw_key.encode()).hexdigest()[:16]

        existing = conn.execute(
            "SELECT price_total FROM listings WHERE offer_id = ?", (offer_id,)
        ).fetchone()

        if not existing:
            stats["new_units"] += 1
        elif existing["price_total"] and unit["price_total"]:
            if abs(existing["price_total"] - unit["price_total"]) > 1:
                stats["price_changes"] += 1

        listing = {
            "offer_id":          offer_id,
            "source":            "otodom",
            "asset_class":       "residential",
            "transaction_type":  "invest_unit",
            "title":             f"{project['name']} — {unit['unit_name']}",
            "url":               f"{project['url']}#unit-{offer_id}",
            "district":          "Mokotów",
            "subdistrict":       project["subdistrict"],
            "address":           None,
            "area_m2":           unit["area_m2"],
            "rooms":             unit["rooms"],
            "floor":             unit["floor"],
            "building_name":     project["name"],
            "building_class":    None,
            "price_total":       unit["price_total"],
            "price_per_m2":      unit["price_per_m2"],
            "currency":          "PLN",
            "advertiser_type":   "developer",
            "parent_project_id": project["project_id"],
            "first_seen":        scrape_ts,
            "last_seen":         scrape_ts,
        }
        upsert_listing(conn, listing)
        insert_snapshot(conn, {
            "offer_id":         offer_id,
            "scrape_date":      scrape_date,
            "scrape_ts":        scrape_ts,
            "active_status":    1,
            "current_price":    unit["price_total"],
            "current_price_m2": unit["price_per_m2"],
        })

        if unit["price_per_m2"]:
            prices_m2.append(unit["price_per_m2"])
        if unit["price_total"]:
            prices_total.append(unit["price_total"])

    upsert_project_snapshot(conn, {
        "project_id":       project["project_id"],
        "scrape_date":      scrape_date,
        "units_available":  len(units),
        "median_price_m2":  median(prices_m2) if prices_m2 else None,
        "avg_price_m2":     sum(prices_m2) / len(prices_m2) if prices_m2 else None,
        "min_price":        min(prices_total) if prices_total else None,
        "max_price":        max(prices_total) if prices_total else None,
    })

    return stats


def main():
    import argparse as _ap
    parser = _ap.ArgumentParser(description="Otodom Developer Scraper")
    parser.add_argument("--show-browser", action="store_true")
    args = parser.parse_args()

    _headless = not args.show_browser
    init_db()
    now = datetime.now(timezone.utc)
    scrape_ts = now.isoformat()
    scrape_date = now.date().isoformat()

    total_units = 0
    total_new = 0
    total_projects = 0

    log.info("[START] Scrapowanie inwestycji deweloperskich Mokotów")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=_headless)
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

        projects = scrape_invest_list(page)

        for i, project in enumerate(projects):
            log.info(f"[PROJECT {i+1}/{len(projects)}] {project['name'][:60]}")

            detail = scrape_project_detail(page, project["url"])
            units = detail["units"]

            # Uzupełnij projekt o dane z detalu
            if detail["developer"]:
                project["developer"] = detail["developer"]
            if detail["address"]:
                project["address"] = detail["address"]

            log.info(f"  → {len(units)} jednostek | deweloper: {project.get('developer') or '—'}")

            if units:
                with get_conn() as conn:
                    s = save_project(conn, project, units, scrape_ts, scrape_date)
                    total_units += len(units)
                    total_new += s["new_units"]
                    total_projects += 1
            else:
                # Zapisz projekt bez jednostek (snapshot z 0)
                with get_conn() as conn:
                    upsert_developer_project(conn, {**project, "first_seen": scrape_ts, "last_seen": scrape_ts})
                    upsert_project_snapshot(conn, {
                        "project_id": project["project_id"],
                        "scrape_date": scrape_date,
                        "units_available": 0,
                        "median_price_m2": None,
                        "avg_price_m2": None,
                        "min_price": None,
                        "max_price": None,
                    })

            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        browser.close()

    log.info(
        f"[DONE] Projekty: {total_projects}/{len(projects)}, "
        f"jednostki: {total_units}, nowe: {total_new}"
    )

    # Status szczery: brak projektów/jednostek = nieudany scrape (awaria sieci/blokada)
    run_status = "ok" if total_projects > 0 else "error"

    with get_conn() as conn:
        log_run(conn, {
            "run_ts":        scrape_ts,
            "source":        "otodom",
            "asset_class":   "developer",
            "url_scraped":   INVEST_LIST_URL,
            "offers_found":  total_units,
            "new_listings":  total_new,
            "delisted":      0,
            "price_changes": 0,
            "status":        run_status,
            "error_msg":     None if run_status == "ok" else "no projects scraped",
        })


if __name__ == "__main__":
    main()
