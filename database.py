"""
database.py — Schemat SQLite i helpery. v2
Ocean Plaza Market Intelligence — Mokotów.
"""

import re
import sqlite3
import hashlib
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "ocean_plaza_intel.db"

OCEAN_PLAZA_LAT = 52.1760
OCEAN_PLAZA_LON = 21.0315

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


def extract_otodom_id(url: str) -> str:
    clean = url.split("?")[0].rstrip("/")
    m = re.search(r"-ID([a-zA-Z0-9]+)$", clean)
    if m:
        return m.group(1)
    return hashlib.md5(clean.encode()).hexdigest()[:16]


def normalize_url(url: str) -> str:
    return url.split("?")[0].rstrip("/")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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

        # Migracja istniejących baz — dodaj kolumny jeśli brakuje
        for col, typedef in [("parent_project_id", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_project ON listings(parent_project_id)")
        except sqlite3.OperationalError:
            pass

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
        conn.execute(
            "UPDATE listings SET is_active = 0, last_seen = ? WHERE offer_id = ?",
            (scrape_date, oid)
        )


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
    conn.execute("""
        INSERT INTO scrape_runs
            (run_ts, source, asset_class, url_scraped, offers_found,
             new_listings, delisted, price_changes, status, error_msg)
        VALUES
            (:run_ts, :source, :asset_class, :url_scraped, :offers_found,
             :new_listings, :delisted, :price_changes, :status, :error_msg)
    """, data)


if __name__ == "__main__":
    init_db()
