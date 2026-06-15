"""
database.py — Schemat SQLite i helpery. v3
Ocean Plaza Market Intelligence — Mokotów.

v3 (Phase 0 — Transaction Intelligence foundations):
  - listings: dodane lat/lon/geocode_confidence/district_norm
  - nowa tabela geo_districts (kontrolowana taksonomia)
  - nowa tabela geocode_cache
  - nowa tabela ingestion_runs (uogólnienie scrape_runs)
  - scrape_runs zachowane jako VIEW (back-compat dla analytics.get_scrape_log)
"""

import re
import math
import sqlite3
import hashlib
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "ocean_plaza_intel.db"

# ul. Domaniewska 50, 02-672 Warszawa (zweryfikowane przez GUGiK PRG, conf=0.8).
OCEAN_PLAZA_LAT = 52.1835
OCEAN_PLAZA_LON = 20.9955

# Strefy Mokotowa jako proxy odległości od Ocean Plaza
ZONE_MAP = {
    "500m":  ["służewiec"],
    "1000m": ["służewiec", "ksawerów", "wierzbno"],
    "2000m": ["służewiec", "ksawerów", "wierzbno", "stary mokotów", "górny mokotów", "sadyba", "siekierki", "mokotów"],
}

COMPETITIVE_SET = {
    "Ocean Plaza":              ["ocean plaza"],
    "Curtis Plaza":             ["curtis plaza", "curtis"],
    "New City":                 ["new city"],
    "Marynarska Business Park": ["marynarska", "marynarska business"],
}

# Seed taksonomii dzielnic Mokotowa — używana przez normalizator district_norm.
# parent_norm, display_name, center_lat, center_lon. Bbox/polygon dorabiamy w Fazie 2.
DISTRICT_SEED = [
    # (district_norm, parent_norm, display_name, center_lat, center_lon)
    ("mokotow",                None,       "Mokotów",         52.1860, 21.0410),
    ("mokotow.sluzewiec",      "mokotow",  "Służewiec",       52.1760, 21.0315),
    ("mokotow.ksawerow",       "mokotow",  "Ksawerów",        52.1830, 21.0290),
    ("mokotow.wyglendow",      "mokotow",  "Wyględów",        52.1880, 21.0250),
    ("mokotow.stegny",         "mokotow",  "Stegny",          52.1810, 21.0670),
    ("mokotow.sadyba",         "mokotow",  "Sadyba",          52.1880, 21.0610),
    ("mokotow.stary_mokotow",  "mokotow",  "Stary Mokotów",   52.2050, 21.0220),
    ("mokotow.gorny_mokotow",  "mokotow",  "Górny Mokotów",   52.1970, 21.0220),
    ("mokotow.wierzbno",       "mokotow",  "Wierzbno",        52.1950, 21.0250),
    ("mokotow.siekierki",      "mokotow",  "Siekierki",       52.1880, 21.0900),
    ("mokotow.sluzew",         "mokotow",  "Służew",          52.1690, 21.0380),
    ("mokotow.czerniakow",     "mokotow",  "Czerniaków",      52.1960, 21.0610),
]

# Aliasy normalizujące tekstowy subdistrict → district_norm.
# Klucze: lowercased. Wartości: district_norm.
DISTRICT_ALIASES = {
    "mokotów":            "mokotow",
    "mokotow":            "mokotow",
    "służewiec":          "mokotow.sluzewiec",
    "sluzewiec":          "mokotow.sluzewiec",
    "służewiec południowy": "mokotow.sluzewiec",
    "służewiec płd.":     "mokotow.sluzewiec",
    "ksawerów":           "mokotow.ksawerow",
    "ksawerow":           "mokotow.ksawerow",
    "wyględów":           "mokotow.wyglendow",
    "wyglendow":          "mokotow.wyglendow",
    "stegny":             "mokotow.stegny",
    "sadyba":             "mokotow.sadyba",
    "stary mokotów":      "mokotow.stary_mokotow",
    "stary mokotow":      "mokotow.stary_mokotow",
    "górny mokotów":      "mokotow.gorny_mokotow",
    "gorny mokotow":      "mokotow.gorny_mokotow",
    "wierzbno":           "mokotow.wierzbno",
    "siekierki":          "mokotow.siekierki",
    "służew":             "mokotow.sluzew",
    "sluzew":             "mokotow.sluzew",
    "czerniaków":         "mokotow.czerniakow",
    "czerniakow":         "mokotow.czerniakow",
}


def normalize_district(subdistrict: str | None) -> str | None:
    if not subdistrict:
        return None
    return DISTRICT_ALIASES.get(subdistrict.strip().lower())


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Dystans w metrach. Używane do stref Ocean Plaza (500/1000/2000m)."""
    if None in (lat1, lon1, lat2, lon2):
        return float("inf")
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def extract_otodom_id(url: str) -> str:
    clean = url.split("?")[0].rstrip("/")
    m = re.search(r"-ID([a-zA-Z0-9]+)$", clean)
    if m:
        return m.group(1)
    return hashlib.md5(clean.encode()).hexdigest()[:16]


def normalize_url(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def _register_udfs(conn: sqlite3.Connection) -> None:
    """Rejestruje UDF dostępne w zapytaniach SQL:
       - haversine_m(lat1, lon1, lat2, lon2)  → odległość w metrach
       - normalize_district_sql(subdistrict)  → district_norm lub NULL
       - ocean_plaza_dist_m(lat, lon)         → dystans od Ocean Plaza
    """
    conn.create_function("haversine_m", 4, haversine_m, deterministic=True)
    conn.create_function(
        "normalize_district_sql", 1,
        lambda s: normalize_district(s) if s is not None else None,
        deterministic=True,
    )
    conn.create_function(
        "ocean_plaza_dist_m", 2,
        lambda lat, lon: haversine_m(OCEAN_PLAZA_LAT, OCEAN_PLAZA_LON, lat, lon)
                          if (lat is not None and lon is not None) else None,
        deterministic=True,
    )
    # Days on market: od daty startowej (published_date lub first_seen) do
    # daty końcowej (delisted_date lub dziś). NIE deterministic — zależy od 'now'.
    conn.create_function("dom_days", 2, _dom_days)


def _dom_days(start_ts, end_ts):
    """Liczba dni między start a end (end=None → dziś). Toleruje ISO i 'YYYY-MM-DD ...'."""
    from datetime import datetime, timezone
    if not start_ts:
        return None
    def _parse(s):
        s = str(s).strip().replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s[:19], fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    start = _parse(start_ts)
    if start is None:
        return None
    end = _parse(end_ts) if end_ts else datetime.now(timezone.utc).replace(tzinfo=None)
    if end is None:
        return None
    return max(0, (end - start).days)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _register_udfs(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            -- Główna tabela ofert
            -- transaction_type: sale | invest_unit | invest_project
            CREATE TABLE IF NOT EXISTS listings (
                offer_id          TEXT PRIMARY KEY,
                source            TEXT NOT NULL DEFAULT 'otodom',
                asset_class       TEXT NOT NULL,
                transaction_type  TEXT NOT NULL,
                title             TEXT,
                url               TEXT UNIQUE NOT NULL,
                district          TEXT,
                subdistrict       TEXT,
                address           TEXT,
                area_m2           REAL,
                rooms             INTEGER,
                floor             TEXT,
                building_name     TEXT,
                building_class    TEXT,
                price_total       REAL,
                price_per_m2      REAL,
                currency          TEXT DEFAULT 'PLN',
                advertiser_type   TEXT,
                parent_project_id TEXT,
                first_seen        TEXT NOT NULL,
                last_seen         TEXT,
                is_active         INTEGER NOT NULL DEFAULT 1
            );

            -- Historia cen per oferta
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_id          TEXT NOT NULL REFERENCES listings(offer_id),
                scrape_date       TEXT NOT NULL,
                scrape_ts         TEXT NOT NULL,
                active_status     INTEGER NOT NULL DEFAULT 1,
                current_price     REAL,
                current_price_m2  REAL,
                UNIQUE(offer_id, scrape_date)
            );

            -- Projekty deweloperskie
            CREATE TABLE IF NOT EXISTS developer_projects (
                project_id    TEXT PRIMARY KEY,
                name          TEXT,
                url           TEXT UNIQUE NOT NULL,
                developer     TEXT,
                subdistrict   TEXT,
                address       TEXT,
                first_seen    TEXT NOT NULL,
                last_seen     TEXT,
                is_active     INTEGER NOT NULL DEFAULT 1
            );

            -- Dzienna historia projektu deweloperskiego
            CREATE TABLE IF NOT EXISTS project_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      TEXT NOT NULL REFERENCES developer_projects(project_id),
                scrape_date     TEXT NOT NULL,
                units_available INTEGER,
                median_price_m2 REAL,
                avg_price_m2    REAL,
                min_price       REAL,
                max_price       REAL,
                UNIQUE(project_id, scrape_date)
            );

            -- Log alertów
            CREATE TABLE IF NOT EXISTS alerts_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_ts    TEXT NOT NULL,
                alert_type  TEXT NOT NULL,
                asset_class TEXT,
                message     TEXT NOT NULL,
                value       REAL,
                threshold   REAL,
                is_new      INTEGER NOT NULL DEFAULT 1
            );

            -- Log runów
            CREATE TABLE IF NOT EXISTS scrape_runs (
                run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                run_ts        TEXT NOT NULL,
                source        TEXT,
                asset_class   TEXT,
                url_scraped   TEXT,
                offers_found  INTEGER,
                new_listings  INTEGER,
                delisted      INTEGER,
                price_changes INTEGER,
                status        TEXT,
                error_msg     TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_offer_id    ON snapshots(offer_id);
            CREATE INDEX IF NOT EXISTS idx_snapshots_scrape_date ON snapshots(scrape_date);
            CREATE INDEX IF NOT EXISTS idx_listings_asset        ON listings(asset_class, transaction_type);
            CREATE INDEX IF NOT EXISTS idx_listings_active       ON listings(is_active);

            CREATE INDEX IF NOT EXISTS idx_proj_snaps_date       ON project_snapshots(project_id, scrape_date);
            CREATE INDEX IF NOT EXISTS idx_alerts_ts             ON alerts_log(alert_ts);

            CREATE TABLE IF NOT EXISTS watchlist (
                offer_id   TEXT PRIMARY KEY REFERENCES listings(offer_id),
                added_ts   TEXT NOT NULL,
                note       TEXT
            );
        """)

        # Migracja istniejących baz — dodaj kolumny jeśli brakuje (idempotentne)
        listings_migrations = [
            ("parent_project_id",        "TEXT"),
            ("latitude",                 "REAL"),
            ("longitude",                "REAL"),
            ("geocode_confidence",       "REAL"),
            ("district_norm",            "TEXT"),
            # Listing Lifecycle Intelligence
            ("listing_status",           "TEXT"),    # ACTIVE | DELISTED | PRICE_REDUCED | PRICE_INCREASED
            ("delisted_date",            "TEXT"),
            ("last_known_price",         "REAL"),
            ("last_known_price_per_m2",  "REAL"),
            ("published_date",           "TEXT"),     # realna data publikacji z Otodom (dateCreated)
        ]
        for col, typedef in listings_migrations:
            try:
                conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass

        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_listings_project ON listings(parent_project_id)",
            "CREATE INDEX IF NOT EXISTS idx_listings_geo     ON listings(latitude, longitude)",
            "CREATE INDEX IF NOT EXISTS idx_listings_dnorm   ON listings(district_norm)",
        ]:
            try:
                conn.execute(idx_sql)
            except sqlite3.OperationalError:
                pass

        # ── Phase 0: Transaction Intelligence foundations ─────────────────
        conn.executescript("""
            -- Kontrolowana taksonomia dzielnic
            CREATE TABLE IF NOT EXISTS geo_districts (
                district_norm  TEXT PRIMARY KEY,
                parent_norm    TEXT,
                display_name   TEXT NOT NULL,
                center_lat     REAL,
                center_lon     REAL,
                bbox_min_lat   REAL,
                bbox_min_lon   REAL,
                bbox_max_lat   REAL,
                bbox_max_lon   REAL,
                polygon_wkt    TEXT
            );

            -- Cache geokodowania (adres → współrzędne)
            CREATE TABLE IF NOT EXISTS geocode_cache (
                address_hash       TEXT PRIMARY KEY,
                address_raw        TEXT,
                address_normalized TEXT,
                latitude           REAL,
                longitude          REAL,
                confidence         REAL,
                provider           TEXT,
                geocoded_at        TEXT NOT NULL
            );

            -- Uogólniony log uruchomień (scrape | import | compute)
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                run_ts            TEXT NOT NULL,
                kind              TEXT NOT NULL DEFAULT 'scrape',
                source            TEXT,
                asset_class       TEXT,
                property_type     TEXT,
                url_scraped       TEXT,
                records_in        INTEGER,
                records_new       INTEGER,
                records_updated   INTEGER,
                records_rejected  INTEGER,
                delisted          INTEGER,
                price_changes     INTEGER,
                status            TEXT,
                error_msg         TEXT,
                duration_ms       INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_ingestion_runs_ts   ON ingestion_runs(run_ts);
            CREATE INDEX IF NOT EXISTS idx_ingestion_runs_kind ON ingestion_runs(kind, source);
        """)

        # Migracja danych: scrape_runs (TABLE) → ingestion_runs, potem zamiana na VIEW.
        # Idempotentne — sprawdzamy czy scrape_runs jest jeszcze tabelą.
        sr_type = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='scrape_runs'"
        ).fetchone()
        if sr_type and sr_type["type"] == "table":
            already = conn.execute(
                "SELECT COUNT(*) c FROM ingestion_runs WHERE kind='scrape'"
            ).fetchone()["c"]
            if already == 0:
                conn.execute("""
                    INSERT INTO ingestion_runs
                        (run_id, run_ts, kind, source, asset_class, url_scraped,
                         records_in, records_new, delisted, price_changes, status, error_msg)
                    SELECT
                         run_id, run_ts, 'scrape', source, asset_class, url_scraped,
                         offers_found, new_listings, delisted, price_changes, status, error_msg
                    FROM scrape_runs
                """)
            conn.execute("DROP TABLE scrape_runs")

        # VIEW scrape_runs zapewnia back-compat dla analytics.get_scrape_log
        # i wszelkich istniejących zapytań SELECT.
        conn.execute("DROP VIEW IF EXISTS scrape_runs")
        conn.execute("""
            CREATE VIEW scrape_runs AS
            SELECT
                run_id,
                run_ts,
                source,
                asset_class,
                url_scraped,
                records_in   AS offers_found,
                records_new  AS new_listings,
                delisted,
                price_changes,
                status,
                error_msg
            FROM ingestion_runs
            WHERE kind = 'scrape'
        """)

        # ── Phase 1: Transaction Intelligence Layer — tabele ──────────────
        conn.executescript("""
            -- Granularny fakt transakcyjny (akt notarialny / rekord ze źródła)
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id              TEXT PRIMARY KEY,
                source                      TEXT NOT NULL,
                source_record_id            TEXT,
                transaction_date            TEXT NOT NULL,
                property_type               TEXT NOT NULL,
                market_type                 TEXT,
                district                    TEXT,
                subdistrict                 TEXT,
                district_norm               TEXT,
                address                     TEXT,
                latitude                    REAL,
                longitude                   REAL,
                geocode_confidence          REAL,
                area_m2                     REAL,
                rooms                       INTEGER,
                floor                       TEXT,
                year_built                  INTEGER,
                transaction_price           REAL,
                transaction_price_per_m2    REAL,
                currency                    TEXT DEFAULT 'PLN',
                imported_at                 TEXT NOT NULL,
                raw_payload                 TEXT
            );

            -- Agregaty czasowe dla źródeł oddających tylko sumy (NBP, GUS, raporty kwartalne)
            -- market_type i district_norm są NOT NULL z sentinelem '' — w SQLite NULL≠NULL,
            -- więc NULL w kolumnie UNIQUE wyłącza deduplikację.
            CREATE TABLE IF NOT EXISTS transaction_market_snapshots (
                snapshot_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date               TEXT NOT NULL,
                period_type                 TEXT NOT NULL,
                source                      TEXT NOT NULL,
                property_type               TEXT NOT NULL,
                market_type                 TEXT NOT NULL DEFAULT '',
                district                    TEXT,
                subdistrict                 TEXT,
                district_norm               TEXT NOT NULL DEFAULT '',
                transaction_count           INTEGER,
                median_price_per_m2         REAL,
                average_price_per_m2        REAL,
                transaction_volume_pln      REAL,
                imported_at                 TEXT NOT NULL,
                UNIQUE(snapshot_date, period_type, source, property_type, market_type, district_norm)
            );

            -- Materializowane spready asking vs. transaction (output Pricing Intelligence Layer)
            CREATE TABLE IF NOT EXISTS pricing_spreads (
                spread_id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date               TEXT NOT NULL,
                property_type               TEXT NOT NULL,
                district                    TEXT,
                subdistrict                 TEXT,
                district_norm               TEXT,
                window_days                 INTEGER NOT NULL,
                asking_price_per_m2         REAL,
                transaction_price_per_m2    REAL,
                spread_pct                  REAL,
                negotiation_index           REAL,
                n_listings                  INTEGER,
                n_transactions              INTEGER,
                confidence                  TEXT,
                computed_at                 TEXT NOT NULL,
                UNIQUE(snapshot_date, property_type, district_norm, window_days)
            );

            CREATE INDEX IF NOT EXISTS idx_tx_date_property ON transactions(transaction_date, property_type);
            CREATE INDEX IF NOT EXISTS idx_tx_dnorm         ON transactions(district_norm);
            CREATE INDEX IF NOT EXISTS idx_tx_geo           ON transactions(latitude, longitude);
            CREATE INDEX IF NOT EXISTS idx_tx_source        ON transactions(source, source_record_id);

            CREATE INDEX IF NOT EXISTS idx_tms_date         ON transaction_market_snapshots(snapshot_date, property_type, district_norm);

            CREATE INDEX IF NOT EXISTS idx_spreads_date     ON pricing_spreads(snapshot_date, property_type, district_norm, window_days);

            -- Listing Lifecycle Intelligence: historia zdarzeń per oferta
            CREATE TABLE IF NOT EXISTS listing_lifecycle_events (
                event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_id        TEXT NOT NULL,
                event_date      TEXT NOT NULL,
                event_type      TEXT NOT NULL,   -- LISTING_CREATED | PRICE_REDUCED | PRICE_INCREASED | DELISTED | RELISTED
                previous_value  REAL,
                new_value       REAL,
                UNIQUE(offer_id, event_date, event_type)
            );
            CREATE INDEX IF NOT EXISTS idx_lifecycle_offer ON listing_lifecycle_events(offer_id);
            CREATE INDEX IF NOT EXISTS idx_lifecycle_type  ON listing_lifecycle_events(event_type, event_date);

            CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(listing_status);
            CREATE INDEX IF NOT EXISTS idx_listings_delisted ON listings(delisted_date);
        """)

        # Seed taksonomii dzielnic (idempotentne)
        for (dn, pn, disp, lat, lon) in DISTRICT_SEED:
            conn.execute("""
                INSERT INTO geo_districts (district_norm, parent_norm, display_name, center_lat, center_lon)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(district_norm) DO UPDATE SET
                    parent_norm  = excluded.parent_norm,
                    display_name = excluded.display_name,
                    center_lat   = COALESCE(excluded.center_lat, geo_districts.center_lat),
                    center_lon   = COALESCE(excluded.center_lon, geo_districts.center_lon)
            """, (dn, pn, disp, lat, lon))

    print(f"[DB] Baza danych gotowa: {DB_PATH}")


def upsert_listing(conn, data: dict):
    conn.execute("""
        INSERT INTO listings
            (offer_id, source, asset_class, transaction_type, title, url,
             district, subdistrict, address, area_m2, rooms, floor,
             building_name, building_class, price_total, price_per_m2,
             currency, advertiser_type, parent_project_id, first_seen, last_seen, is_active)
        VALUES
            (:offer_id, :source, :asset_class, :transaction_type, :title, :url,
             :district, :subdistrict, :address, :area_m2, :rooms, :floor,
             :building_name, :building_class, :price_total, :price_per_m2,
             :currency, :advertiser_type, :parent_project_id, :first_seen, :last_seen, 1)
        ON CONFLICT(offer_id) DO UPDATE SET
            price_total       = excluded.price_total,
            price_per_m2      = excluded.price_per_m2,
            title             = excluded.title,
            last_seen         = excluded.last_seen,
            is_active         = 1
    """, data)


def insert_snapshot(conn, data: dict):
    conn.execute("""
        INSERT OR IGNORE INTO snapshots
            (offer_id, scrape_date, scrape_ts, active_status, current_price, current_price_m2)
        VALUES
            (:offer_id, :scrape_date, :scrape_ts, :active_status, :current_price, :current_price_m2)
    """, data)


def mark_delisted(conn, offer_ids: list, scrape_date: str, scrape_ts: str):
    for oid in offer_ids:
        conn.execute("""
            INSERT OR IGNORE INTO snapshots
                (offer_id, scrape_date, scrape_ts, active_status, current_price, current_price_m2)
            VALUES (?, ?, ?, 0, NULL, NULL)
        """, (oid, scrape_date, scrape_ts))
        # Ostatnia znana cena (przed delistingiem) z najświeższego aktywnego snapshotu
        last = conn.execute("""
            SELECT current_price, current_price_m2 FROM snapshots
            WHERE offer_id=? AND active_status=1 AND current_price IS NOT NULL
            ORDER BY scrape_date DESC LIMIT 1
        """, (oid,)).fetchone()
        last_p = last["current_price"] if last else None
        last_pm2 = last["current_price_m2"] if last else None
        conn.execute("""
            UPDATE listings SET
                is_active = 0,
                last_seen = ?,
                listing_status = 'DELISTED',
                delisted_date = ?,
                last_known_price = COALESCE(?, last_known_price),
                last_known_price_per_m2 = COALESCE(?, last_known_price_per_m2)
            WHERE offer_id = ?
        """, (scrape_date, scrape_date, last_p, last_pm2, oid))
        insert_lifecycle_event(conn, oid, scrape_date, "DELISTED", last_p, None)


def upsert_developer_project(conn, data: dict):
    conn.execute("""
        INSERT INTO developer_projects
            (project_id, name, url, developer, subdistrict, address, first_seen, last_seen, is_active)
        VALUES
            (:project_id, :name, :url, :developer, :subdistrict, :address, :first_seen, :last_seen, 1)
        ON CONFLICT(project_id) DO UPDATE SET
            name       = excluded.name,
            developer  = COALESCE(excluded.developer, developer_projects.developer),
            address    = COALESCE(excluded.address, developer_projects.address),
            last_seen  = excluded.last_seen,
            is_active  = 1
    """, data)


def upsert_project_snapshot(conn, data: dict):
    conn.execute("""
        INSERT OR REPLACE INTO project_snapshots
            (project_id, scrape_date, units_available, median_price_m2, avg_price_m2, min_price, max_price)
        VALUES
            (:project_id, :scrape_date, :units_available, :median_price_m2, :avg_price_m2, :min_price, :max_price)
    """, data)


def get_last_active_offer_ids(conn, asset_class: str, transaction_type: str = None) -> set:
    if transaction_type:
        row = conn.execute("""
            SELECT MAX(s.scrape_date) as last_date
            FROM snapshots s JOIN listings l ON l.offer_id = s.offer_id
            WHERE l.asset_class = ? AND l.transaction_type = ?
        """, (asset_class, transaction_type)).fetchone()
    else:
        row = conn.execute("""
            SELECT MAX(s.scrape_date) as last_date
            FROM snapshots s JOIN listings l ON l.offer_id = s.offer_id
            WHERE l.asset_class = ?
        """, (asset_class,)).fetchone()

    if not row or not row["last_date"]:
        return set()

    if transaction_type:
        rows = conn.execute("""
            SELECT s.offer_id FROM snapshots s JOIN listings l ON l.offer_id = s.offer_id
            WHERE s.scrape_date = ? AND s.active_status = 1
              AND l.asset_class = ? AND l.transaction_type = ?
        """, (row["last_date"], asset_class, transaction_type)).fetchall()
    else:
        rows = conn.execute("""
            SELECT s.offer_id FROM snapshots s JOIN listings l ON l.offer_id = s.offer_id
            WHERE s.scrape_date = ? AND s.active_status = 1 AND l.asset_class = ?
        """, (row["last_date"], asset_class)).fetchall()

    return {r["offer_id"] for r in rows}


def log_run(conn, data: dict):
    """Loguje run scrapera/importera do ingestion_runs.

    Akceptuje legacy klucze (offers_found, new_listings) z istniejących scraperów
    i mapuje na records_in / records_new. Domyślne kind='scrape'.
    """
    payload = {
        "run_ts":           data.get("run_ts"),
        "kind":             data.get("kind", "scrape"),
        "source":           data.get("source"),
        "asset_class":      data.get("asset_class"),
        "property_type":    data.get("property_type"),
        "url_scraped":      data.get("url_scraped"),
        "records_in":       data.get("records_in",       data.get("offers_found")),
        "records_new":      data.get("records_new",      data.get("new_listings")),
        "records_updated":  data.get("records_updated"),
        "records_rejected": data.get("records_rejected"),
        "delisted":         data.get("delisted"),
        "price_changes":    data.get("price_changes"),
        "status":           data.get("status"),
        "error_msg":        data.get("error_msg"),
        "duration_ms":      data.get("duration_ms"),
    }
    conn.execute("""
        INSERT INTO ingestion_runs
            (run_ts, kind, source, asset_class, property_type, url_scraped,
             records_in, records_new, records_updated, records_rejected,
             delisted, price_changes, status, error_msg, duration_ms)
        VALUES
            (:run_ts, :kind, :source, :asset_class, :property_type, :url_scraped,
             :records_in, :records_new, :records_updated, :records_rejected,
             :delisted, :price_changes, :status, :error_msg, :duration_ms)
    """, payload)


def insert_lifecycle_event(conn, offer_id: str, event_date: str, event_type: str,
                           previous_value=None, new_value=None):
    """Idempotentny zapis zdarzenia lifecycle (UNIQUE offer_id+date+type)."""
    conn.execute("""
        INSERT OR IGNORE INTO listing_lifecycle_events
            (offer_id, event_date, event_type, previous_value, new_value)
        VALUES (?, ?, ?, ?, ?)
    """, (offer_id, event_date, event_type, previous_value, new_value))


def upsert_transaction(conn, data: dict):
    """Idempotentny upsert transakcji. transaction_id musi być stabilny w czasie.

    Konwencja: transaction_id = f"{source}:{source_record_id}" (jeśli źródło ma ID),
    inaczej hash treści (źródło może podać własną strategię).
    """
    conn.execute("""
        INSERT INTO transactions
            (transaction_id, source, source_record_id, transaction_date,
             property_type, market_type, district, subdistrict, district_norm,
             address, latitude, longitude, geocode_confidence,
             area_m2, rooms, floor, year_built,
             transaction_price, transaction_price_per_m2, currency,
             imported_at, raw_payload)
        VALUES
            (:transaction_id, :source, :source_record_id, :transaction_date,
             :property_type, :market_type, :district, :subdistrict, :district_norm,
             :address, :latitude, :longitude, :geocode_confidence,
             :area_m2, :rooms, :floor, :year_built,
             :transaction_price, :transaction_price_per_m2, :currency,
             :imported_at, :raw_payload)
        ON CONFLICT(transaction_id) DO UPDATE SET
            transaction_date          = excluded.transaction_date,
            property_type             = excluded.property_type,
            market_type               = COALESCE(excluded.market_type, transactions.market_type),
            district                  = COALESCE(excluded.district, transactions.district),
            subdistrict               = COALESCE(excluded.subdistrict, transactions.subdistrict),
            district_norm             = COALESCE(excluded.district_norm, transactions.district_norm),
            address                   = COALESCE(excluded.address, transactions.address),
            latitude                  = COALESCE(excluded.latitude, transactions.latitude),
            longitude                 = COALESCE(excluded.longitude, transactions.longitude),
            geocode_confidence        = COALESCE(excluded.geocode_confidence, transactions.geocode_confidence),
            area_m2                   = COALESCE(excluded.area_m2, transactions.area_m2),
            rooms                     = COALESCE(excluded.rooms, transactions.rooms),
            floor                     = COALESCE(excluded.floor, transactions.floor),
            year_built                = COALESCE(excluded.year_built, transactions.year_built),
            transaction_price         = excluded.transaction_price,
            transaction_price_per_m2  = excluded.transaction_price_per_m2,
            raw_payload               = excluded.raw_payload
    """, data)


def upsert_transaction_market_snapshot(conn, data: dict):
    # Sentinele '' zamiast NULL — NULL w kolumnach UNIQUE wyłącza deduplikację w SQLite
    payload = dict(data)
    payload["market_type"] = payload.get("market_type") or ""
    payload["district_norm"] = payload.get("district_norm") or ""
    conn.execute("""
        INSERT INTO transaction_market_snapshots
            (snapshot_date, period_type, source, property_type, market_type,
             district, subdistrict, district_norm,
             transaction_count, median_price_per_m2, average_price_per_m2,
             transaction_volume_pln, imported_at)
        VALUES
            (:snapshot_date, :period_type, :source, :property_type, :market_type,
             :district, :subdistrict, :district_norm,
             :transaction_count, :median_price_per_m2, :average_price_per_m2,
             :transaction_volume_pln, :imported_at)
        ON CONFLICT(snapshot_date, period_type, source, property_type, market_type, district_norm)
        DO UPDATE SET
            transaction_count       = excluded.transaction_count,
            median_price_per_m2     = excluded.median_price_per_m2,
            average_price_per_m2    = excluded.average_price_per_m2,
            transaction_volume_pln  = excluded.transaction_volume_pln,
            imported_at             = excluded.imported_at
    """, payload)


def upsert_pricing_spread(conn, data: dict):
    conn.execute("""
        INSERT INTO pricing_spreads
            (snapshot_date, property_type, district, subdistrict, district_norm,
             window_days, asking_price_per_m2, transaction_price_per_m2,
             spread_pct, negotiation_index, n_listings, n_transactions,
             confidence, computed_at)
        VALUES
            (:snapshot_date, :property_type, :district, :subdistrict, :district_norm,
             :window_days, :asking_price_per_m2, :transaction_price_per_m2,
             :spread_pct, :negotiation_index, :n_listings, :n_transactions,
             :confidence, :computed_at)
        ON CONFLICT(snapshot_date, property_type, district_norm, window_days)
        DO UPDATE SET
            asking_price_per_m2       = excluded.asking_price_per_m2,
            transaction_price_per_m2  = excluded.transaction_price_per_m2,
            spread_pct                = excluded.spread_pct,
            negotiation_index         = excluded.negotiation_index,
            n_listings                = excluded.n_listings,
            n_transactions            = excluded.n_transactions,
            confidence                = excluded.confidence,
            computed_at               = excluded.computed_at
    """, data)


if __name__ == "__main__":
    init_db()
