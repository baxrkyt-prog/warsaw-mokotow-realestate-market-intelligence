"""
collectors/geocoding/base.py — Geocoder ABC + cache + normalizacja adresu.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class GeocodeResult:
    latitude: float | None
    longitude: float | None
    confidence: float
    provider: str
    address_normalized: str | None = None
    raw: dict | None = None


_STREET_PREFIX_RE = re.compile(r"^(ul\.|ulica|al\.|aleja|pl\.|plac|os\.|osiedle)\s+", re.IGNORECASE)
_POSTCODE_RE = re.compile(r"\b\d{2}-\d{3}\b")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_address(addr: str | None) -> str:
    """Lowercase, usuń kod pocztowy, usuń przedrostek ulicy, zwiń whitespace."""
    if not addr:
        return ""
    s = addr.strip().lower()
    s = _POSTCODE_RE.sub("", s)
    s = _STREET_PREFIX_RE.sub("", s)
    s = s.replace(",", " ")
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def address_hash(addr_normalized: str, provider: str = "") -> str:
    """Cache key per (provider, normalized address). Inaczej drugi geocoder dostaje
    cache hit z wyniku pierwszego i nigdy nie ma szansy spróbować."""
    key = f"{provider}::{addr_normalized}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


class Geocoder(ABC):
    """Wspólny kontrakt geokoderów. Cache-first."""

    provider: str = ""

    @abstractmethod
    def lookup(self, address: str) -> GeocodeResult:
        """Surowe zapytanie do API. Bez cache."""

    def resolve(self, address: str) -> GeocodeResult:
        """Cache-first lookup. Zapisuje wynik do geocode_cache."""
        if not address:
            return GeocodeResult(None, None, 0.0, self.provider, None)
        norm = normalize_address(address)
        if not norm:
            return GeocodeResult(None, None, 0.0, self.provider, None)
        h = address_hash(norm, self.provider)

        from database import get_conn
        with get_conn() as conn:
            cached = conn.execute(
                "SELECT latitude, longitude, confidence, provider FROM geocode_cache WHERE address_hash = ?",
                (h,),
            ).fetchone()
            if cached:
                return GeocodeResult(
                    latitude=cached["latitude"],
                    longitude=cached["longitude"],
                    confidence=cached["confidence"],
                    provider=cached["provider"],
                    address_normalized=norm,
                )

        # Cache miss → live lookup
        result = self.lookup(address)
        result.address_normalized = norm

        with get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO geocode_cache
                    (address_hash, address_raw, address_normalized,
                     latitude, longitude, confidence, provider, geocoded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                h, address, norm,
                result.latitude, result.longitude, result.confidence,
                result.provider, datetime.now(timezone.utc).isoformat(),
            ))

        return result
