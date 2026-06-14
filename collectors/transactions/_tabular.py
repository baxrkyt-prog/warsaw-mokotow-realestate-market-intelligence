"""
collectors/transactions/_tabular.py — wspólna logika importu transakcji z arkuszy
tabelarycznych (CSV / XLSX). Konfig sterowany JSON-em — patrz docs poniżej.

Konfig (JSON):
{
  "source":                 "manual_csv_2024_q4",   # stabilny ID źródła
  "property_type":          "residential",          # residential | office | land | commercial
  "market_type":            "secondary",            # primary | secondary | null
  "default_district":       "Mokotów",
  "default_subdistrict":    null,                   # gdy nieobecny w danych
  "default_district_norm":  "mokotow",              # gdy normalizacja zawodzi
  "currency":               "PLN",
  "date_format":            "%Y-%m-%d",             # strftime
  "skip_rows":              0,                      # pomiń N pierwszych wierszy
  "sheet":                  null,                   # tylko XLSX
  "delimiter":              ",",                    # tylko CSV
  "encoding":               "utf-8",                # tylko CSV
  "columns": {                                       # docelowa_kolumna → kolumna_w_pliku
      "transaction_date":   "data_aktu",
      "address":            "adres",
      "area_m2":            "powierzchnia",
      "rooms":              "liczba_pokoi",
      "floor":              "pietro",
      "year_built":         "rok_budowy",
      "transaction_price":  "cena",
      "subdistrict":        "dzielnica",
      "latitude":           "lat",
      "longitude":          "lon",
      "source_record_id":   "id"
  },
  "id_strategy":            "source_record_id"      # source_record_id | hash
}

Sanity floors zależne od property_type — rekordy poza zakresem trafiają do records_rejected.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from database import get_conn, normalize_district, upsert_transaction


# Sanity floor / ceiling per property_type (PLN/m²). Phase 4 doda winsoryzację.
PRICE_M2_BOUNDS = {
    "residential": (1000, 100000),
    "office":      (2000, 200000),
    "land":        (50,    50000),
    "commercial":  (1000, 200000),
}


@dataclass
class ImportConfig:
    source: str
    property_type: str
    market_type: str | None = None
    default_district: str | None = None
    default_subdistrict: str | None = None
    default_district_norm: str | None = None
    currency: str = "PLN"
    date_format: str = "%Y-%m-%d"
    skip_rows: int = 0
    sheet: str | None = None
    delimiter: str = ","
    encoding: str = "utf-8"
    columns: dict[str, str] = None
    id_strategy: str = "source_record_id"
    geocode: bool = False          # geokoduj rekordy z adresem (GUGiK→Nominatim, cache-first)
    geocode_limit: int = 500       # maks. LIVE wywołań geocodera na import (cache nie liczy się)

    @classmethod
    def from_file(cls, path: str | Path) -> "ImportConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            source=data["source"],
            property_type=data["property_type"],
            market_type=data.get("market_type"),
            default_district=data.get("default_district"),
            default_subdistrict=data.get("default_subdistrict"),
            default_district_norm=data.get("default_district_norm"),
            currency=data.get("currency", "PLN"),
            date_format=data.get("date_format", "%Y-%m-%d"),
            skip_rows=int(data.get("skip_rows", 0)),
            sheet=data.get("sheet"),
            delimiter=data.get("delimiter", ","),
            encoding=data.get("encoding", "utf-8"),
            columns=data.get("columns", {}),
            id_strategy=data.get("id_strategy", "source_record_id"),
            geocode=bool(data.get("geocode", False)),
            geocode_limit=int(data.get("geocode_limit", 500)),
        )


def _to_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(val: Any) -> int | None:
    f = _to_float(val)
    return int(f) if f is not None else None


def _to_date(val: Any, fmt: str) -> str | None:
    """Zwraca ISO date string (YYYY-MM-DD) lub None."""
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    # openpyxl może zwrócić date
    if hasattr(val, "isoformat") and not isinstance(val, str):
        try:
            return val.isoformat()[:10]
        except Exception:
            pass
    s = str(val).strip()
    # 1) ISO bez parsowania
    try:
        return datetime.fromisoformat(s[:19]).date().isoformat()
    except ValueError:
        pass
    # 2) skonfigurowany format
    try:
        return datetime.strptime(s, fmt).date().isoformat()
    except ValueError:
        return None


def _build_transaction_id(source: str, raw_row: dict, columns: dict, strategy: str) -> str:
    if strategy == "source_record_id" and "source_record_id" in columns:
        src_col = columns["source_record_id"]
        srid = raw_row.get(src_col)
        if srid:
            return f"{source}:{srid}"
    # fallback hash
    payload = json.dumps(raw_row, sort_keys=True, default=str)
    return f"{source}:{hashlib.sha1(payload.encode()).hexdigest()[:16]}"


def _validate_and_normalize(
    raw_row: dict,
    cfg: ImportConfig,
    on_reject,
) -> dict | None:
    """Zwraca słownik gotowy do upsert_transaction lub None (rekord odrzucony)."""
    cols = cfg.columns
    get = lambda key: raw_row.get(cols[key]) if key in cols else None

    tx_date = _to_date(get("transaction_date"), cfg.date_format)
    if not tx_date:
        on_reject("invalid_transaction_date")
        return None

    area = _to_float(get("area_m2"))
    price = _to_float(get("transaction_price"))
    if area is None or area <= 0:
        on_reject("invalid_area_m2")
        return None
    if price is None or price <= 0:
        on_reject("invalid_transaction_price")
        return None

    price_m2 = price / area
    lo, hi = PRICE_M2_BOUNDS.get(cfg.property_type, (0, float("inf")))
    if not (lo <= price_m2 <= hi):
        on_reject(f"price_per_m2_out_of_bounds[{lo}..{hi}]")
        return None

    subdistrict = (get("subdistrict") or cfg.default_subdistrict)
    dnorm = normalize_district(subdistrict) or cfg.default_district_norm

    tx_id = _build_transaction_id(cfg.source, raw_row, cols, cfg.id_strategy)
    src_rid = str(get("source_record_id")) if "source_record_id" in cols and get("source_record_id") else None

    market_type = cfg.market_type
    if "market_type" in cols:
        raw_mt = str(get("market_type") or "").strip().lower()
        if raw_mt in ("primary", "pierwotny"):
            market_type = "primary"
        elif raw_mt in ("secondary", "wtórny", "wtorny"):
            market_type = "secondary"

    return {
        "transaction_id":           tx_id,
        "source":                   cfg.source,
        "source_record_id":         src_rid,
        "transaction_date":         tx_date,
        "property_type":            cfg.property_type,
        "market_type":              market_type,
        "district":                 get("district") or cfg.default_district,
        "subdistrict":              subdistrict,
        "district_norm":            dnorm,
        "address":                  get("address"),
        "latitude":                 _to_float(get("latitude")),
        "longitude":                _to_float(get("longitude")),
        "geocode_confidence":       None,
        "area_m2":                  area,
        "rooms":                    _to_int(get("rooms")),
        "floor":                    str(get("floor")) if get("floor") is not None else None,
        "year_built":               _to_int(get("year_built")),
        "transaction_price":        price,
        "transaction_price_per_m2": round(price_m2, 2),
        "currency":                 cfg.currency,
        "imported_at":              datetime.now(timezone.utc).isoformat(),
        "raw_payload":              json.dumps(raw_row, default=str, ensure_ascii=False),
    }


class _ImportGeocoder:
    """Lazy geokoder z budżetem live-calls. Cache hity nie zużywają budżetu."""

    def __init__(self, limit: int):
        self.limit = limit
        self.live_used = 0
        self.geocoded = 0
        self._primary = None
        self._fallback = None

    def _init_providers(self):
        from collectors.geocoding import GugikGeocoder, NominatimGeocoder
        self._primary = GugikGeocoder()
        self._fallback = NominatimGeocoder()

    def _is_cached(self, address: str) -> bool:
        from collectors.geocoding.base import normalize_address, address_hash
        norm = normalize_address(address)
        if not norm:
            return False
        with get_conn() as conn:
            for provider in ("gugik", "nominatim"):
                if conn.execute(
                    "SELECT 1 FROM geocode_cache WHERE address_hash = ?",
                    (address_hash(norm, provider),),
                ).fetchone():
                    return True
        return False

    def resolve(self, address: str):
        """Zwraca (lat, lon, confidence) lub (None, None, None)."""
        if self._primary is None:
            self._init_providers()
        cached = self._is_cached(address)
        if not cached and self.live_used >= self.limit:
            return None, None, None
        if not cached:
            self.live_used += 1
        res = self._primary.resolve(address)
        if res.latitude is None or res.confidence < 0.5:
            res2 = self._fallback.resolve(address)
            if res2.latitude is not None and res2.confidence >= res.confidence:
                res = res2
        if res.latitude is None:
            return None, None, None
        self.geocoded += 1
        return res.latitude, res.longitude, res.confidence


def import_rows(
    rows: Iterator[dict],
    cfg: ImportConfig,
    result,
    dry_run: bool = False,
) -> None:
    """Iteruje po wierszach, waliduje, wykonuje upsert. Updatuje `result` in-place."""
    new_count = 0
    upd_count = 0
    geocoder = _ImportGeocoder(cfg.geocode_limit) if cfg.geocode else None

    with get_conn() as conn:
        existing_ids = set()
        if not dry_run:
            existing_ids = {
                r["transaction_id"]
                for r in conn.execute(
                    "SELECT transaction_id FROM transactions WHERE source = ?",
                    (cfg.source,),
                ).fetchall()
            }
        payloads = []
        for raw in rows:
            result.records_in += 1
            payload = _validate_and_normalize(raw, cfg, result.reject)
            if payload is None:
                continue
            payloads.append(payload)

    # Geokodowanie POZA transakcją DB (sieć + osobne connection geocodera)
    if geocoder is not None and not dry_run:
        for payload in payloads:
            if payload["latitude"] is not None or not payload["address"]:
                continue
            addr = payload["address"]
            # Dodaj kontekst miasta jeśli go brak — poprawia trafność GUGiK
            if "warszawa" not in addr.lower():
                addr = f"{addr}, Warszawa"
            lat, lon, conf = geocoder.resolve(addr)
            if lat is not None:
                payload["latitude"] = lat
                payload["longitude"] = lon
                payload["geocode_confidence"] = conf

    if not dry_run:
        with get_conn() as conn:
            for payload in payloads:
                is_new = payload["transaction_id"] not in existing_ids
                upsert_transaction(conn, payload)
                if is_new:
                    new_count += 1
                    existing_ids.add(payload["transaction_id"])
                else:
                    upd_count += 1

    result.records_new = new_count
    result.records_updated = upd_count
    result.extras["property_type"] = cfg.property_type
    if geocoder is not None:
        result.extras["geocoded"] = geocoder.geocoded
        result.extras["geocode_live_calls"] = geocoder.live_used
