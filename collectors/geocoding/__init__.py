"""
collectors.geocoding — warstwa geokodowania źródeł adresowych dla platformy.

Providery (kolejność preferencji dla PL):
  1. gugik  — Państwowy Rejestr Granic (GUGiK), oficjalny, darmowy, brak rate-limit policy
  2. nominatim — OSM, fallback (rate-limit 1 req/s, ToS PL ostrożne)

Confidence scale:
  1.0  — addressPoint (numer budynku)
  0.8  — ulica (środek odcinka)
  0.5  — dzielnica / centroid
  0.2  — miasto
  0.0  — brak

Wszystkie zapytania przechodzą przez geocode_cache (sha1 znormalizowanego adresu).
"""

from .base import Geocoder, GeocodeResult, normalize_address, address_hash
from .gugik import GugikGeocoder
from .nominatim import NominatimGeocoder

__all__ = [
    "Geocoder", "GeocodeResult",
    "normalize_address", "address_hash",
    "GugikGeocoder", "NominatimGeocoder",
]
