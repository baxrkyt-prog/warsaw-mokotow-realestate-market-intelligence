"""
collectors/geocoding/nominatim.py — fallback dla GUGiK.

OSM Nominatim: https://nominatim.openstreetmap.org/search?q=...&format=json&limit=1
Rate-limit: 1 req/s (ToS). Klasa ma wbudowany throttle.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from .base import Geocoder, GeocodeResult


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TIMEOUT_S = 10
RATE_LIMIT_S = 1.05


class NominatimGeocoder(Geocoder):
    provider = "nominatim"
    _last_call_ts: float = 0.0

    def lookup(self, address: str) -> GeocodeResult:
        # Throttle
        elapsed = time.time() - NominatimGeocoder._last_call_ts
        if elapsed < RATE_LIMIT_S:
            time.sleep(RATE_LIMIT_S - elapsed)
        NominatimGeocoder._last_call_ts = time.time()

        params = {
            "q": address,
            "format": "json",
            "limit": "1",
            "addressdetails": "1",
            "countrycodes": "pl",
        }
        url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "OceanPlazaMI/1.0 (contact: market-intelligence)"}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:
            return GeocodeResult(None, None, 0.0, self.provider, raw={"error": str(e)})

        if not payload:
            return GeocodeResult(None, None, 0.0, self.provider, raw={"empty": True})

        first = payload[0]
        try:
            lat = float(first["lat"])
            lon = float(first["lon"])
        except (KeyError, ValueError):
            return GeocodeResult(None, None, 0.0, self.provider, raw=first)

        # Confidence z `type` / addressdetails
        addr = first.get("address") or {}
        if first.get("type") in ("house", "building") or addr.get("house_number"):
            conf = 1.0
        elif first.get("type") in ("street", "road") or addr.get("road"):
            conf = 0.8
        elif first.get("type") in ("suburb", "neighbourhood", "quarter") or addr.get("suburb"):
            conf = 0.5
        else:
            conf = 0.3

        return GeocodeResult(
            latitude=lat,
            longitude=lon,
            confidence=conf,
            provider=self.provider,
            raw=first,
        )
