"""
collectors/geocoding/gugik.py — geokoder oparty o usługi GUGiK / PRG.

Endpoint: https://services.gugik.gov.pl/uug/?request=GetAddress&address=...
Zwraca punkt EPSG:2180 (PL-1992); konwersja na WGS84 przez pyproj jeśli dostępne.
Fallback: usługa Geoportal /map zwraca WGS84 dla niektórych endpointów.

Tu używamy:
   https://services.gugik.gov.pl/uug/?request=GetAddressReverse  (ale nam potrzebny forward)
   https://services.gugik.gov.pl/uug/?request=GetAddress&address={query}&srid=4326

`srid=4326` wymusza WGS84 w odpowiedzi.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .base import Geocoder, GeocodeResult


GUGIK_URL = "https://services.gugik.gov.pl/uug/"
TIMEOUT_S = 8


class GugikGeocoder(Geocoder):
    provider = "gugik"

    def _format_query(self, address: str) -> str:
        """GUGiK chce 'Miasto, ulica numer'. Jeśli nie ma 'Warszawa', dodajemy.
        Usuwamy też 'ul.'/'al.'/kodów pocztowych — GUGiK to gubi."""
        import re
        a = address.strip()
        a = re.sub(r"\b\d{2}-\d{3}\b", "", a)                       # kod pocztowy
        a = re.sub(r"^(ul\.|ulica|al\.|aleja|pl\.|plac)\s+",
                   "", a, flags=re.IGNORECASE)
        if "warszawa" not in a.lower():
            a = f"Warszawa, {a}"
        else:
            # Wyłuskaj 'Warszawa' na front jeśli jest gdzie indziej
            parts = [p.strip() for p in a.split(",") if p.strip()]
            wpart = next((p for p in parts if "warszawa" in p.lower()), None)
            if wpart and parts[0] != wpart:
                parts.remove(wpart)
                parts.insert(0, wpart)
                a = ", ".join(parts)
        return a.strip()

    def lookup(self, address: str) -> GeocodeResult:
        query = self._format_query(address)
        params = {
            "request": "GetAddress",
            "address": query,
            "srid": "4326",
            "maxresults": "1",
        }
        url = f"{GUGIK_URL}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "OceanPlazaMI/1.0 (+market intelligence)"}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:
            return GeocodeResult(None, None, 0.0, self.provider, raw={"error": str(e)})

        # Struktura GUGiK uug: {"found": N, "results": {"1": {"x": lon, "y": lat, "city": ..., ...}}}
        results = payload.get("results") or {}
        if not results:
            return GeocodeResult(None, None, 0.0, self.provider, raw=payload)

        first_key = next(iter(results))
        first = results[first_key]
        lat = first.get("y")
        lon = first.get("x")
        if lat is None or lon is None:
            return GeocodeResult(None, None, 0.0, self.provider, raw=payload)

        # Confidence — GUGiK podaje pole `accuracy` (0.0–1.0), mapujemy 1:1
        try:
            conf = float(first.get("accuracy", 0))
        except (TypeError, ValueError):
            conf = 0.0
        if conf == 0.0:
            # Fallback heurystyka jeśli accuracy brak
            if first.get("number"):
                conf = 1.0
            elif first.get("street"):
                conf = 0.8
            elif first.get("city"):
                conf = 0.5
            else:
                conf = 0.3

        return GeocodeResult(
            latitude=float(lat),
            longitude=float(lon),
            confidence=conf,
            provider=self.provider,
            raw=first,
        )
