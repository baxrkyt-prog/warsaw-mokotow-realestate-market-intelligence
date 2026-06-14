"""
collectors.maintenance.backfill_listings_geo — backfill geokodowania dla `listings`.

Trzystopniowy:
  1. district_norm — offline, deterministyczny (normalize_district(subdistrict))
  2. centroid lat/lon (conf 0.5) — z geo_districts.center_*, dla wszystkich z district_norm
  3. real geocoding (conf 0.7–1.0) — dla rekordów z `building_name` lub gdy
     --use-title parsing tytułu wydobędzie ulicę. Wynik nadpisuje centroid.

Limity:
  --only-active             tylko is_active=1 (domyślnie tak)
  --asset-class CLASS       office | residential | all
  --geocode-limit N         maks. live wywołań geocodera (ochrona przed flood)
  --provider gugik|nominatim (domyślnie gugik)
  --dry-run                 nic nie pisze do listings

Statystyki w CollectorResult.extras:
  dnorm_set, centroid_set, geocoded_high, building_attempts, building_misses
"""

from __future__ import annotations

import argparse

from collectors.base import Collector, CollectorResult
from collectors.registry import register


@register
class ListingsGeoBackfill(Collector):
    source = "backfill_listings_geo"
    kind = "maintenance"
    schema_version = 1
    description = "Backfill listings.district_norm + lat/lon (centroid + real where possible)"

    @classmethod
    def add_cli_args(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--asset-class", default="all",
                            choices=["office", "residential", "all"])
        parser.add_argument("--only-active", action="store_true", default=True)
        parser.add_argument("--include-inactive", action="store_true",
                            help="Backfill też nieaktywnych (domyślnie tylko aktywne)")
        parser.add_argument("--geocode-limit", type=int, default=200,
                            help="Maks. live wywołań geocodera (chroni przed floodem)")
        parser.add_argument("--provider", default="gugik",
                            choices=["gugik", "nominatim"])
        parser.add_argument("--no-fallback", action="store_true",
                            help="Wyłącz fallback do Nominatim gdy provider miss")
        parser.add_argument("--dry-run", action="store_true")

    def run(self, **kwargs) -> CollectorResult:
        from database import get_conn, normalize_district
        from collectors.geocoding import GugikGeocoder, NominatimGeocoder

        result = CollectorResult(source=self.source, kind="maintenance")
        result.extras["asset_class"] = kwargs.get("asset_class") or "all"

        active_only = not kwargs.get("include_inactive", False)
        ac_filter = ""
        params: dict = {}
        if kwargs["asset_class"] != "all":
            ac_filter = "AND asset_class = :ac"
            params["ac"] = kwargs["asset_class"]
        active_filter = "AND is_active = 1" if active_only else ""
        dry = kwargs.get("dry_run", False)
        geocode_budget = int(kwargs["geocode_limit"])

        primary = GugikGeocoder() if kwargs["provider"] == "gugik" else NominatimGeocoder()
        fallback = NominatimGeocoder() if (kwargs["provider"] == "gugik"
                                            and not kwargs.get("no_fallback")) else None

        dnorm_set = 0
        centroid_set = 0
        geocoded_high = 0
        building_attempts = 0
        building_misses = 0

        # 1+2: district_norm + centroid w jednym przebiegu
        with get_conn() as conn:
            # Centroidy
            centroids = {
                r["district_norm"]: (r["center_lat"], r["center_lon"])
                for r in conn.execute("SELECT district_norm, center_lat, center_lon FROM geo_districts").fetchall()
                if r["center_lat"] is not None
            }

            rows = conn.execute(f"""
                SELECT offer_id, asset_class, subdistrict, district_norm,
                       latitude, longitude, geocode_confidence, building_name
                FROM listings
                WHERE 1=1 {ac_filter} {active_filter}
            """, params).fetchall()

            result.records_in = len(rows)

            for row in rows:
                offer_id = row["offer_id"]

                # 1) district_norm
                dn = row["district_norm"]
                if not dn:
                    dn = normalize_district(row["subdistrict"])
                    if dn:
                        if not dry:
                            conn.execute(
                                "UPDATE listings SET district_norm = ? WHERE offer_id = ?",
                                (dn, offer_id),
                            )
                        dnorm_set += 1

                # 2) centroid lat/lon (gdy brak współrzędnych i znamy dzielnicę)
                if row["latitude"] is None and dn and dn in centroids:
                    lat, lon = centroids[dn]
                    if not dry:
                        conn.execute(
                            "UPDATE listings SET latitude=?, longitude=?, geocode_confidence=? WHERE offer_id=?",
                            (lat, lon, 0.5, offer_id),
                        )
                    centroid_set += 1

        # 3) Real geocoding dla rekordów z building_name (poza tx commitem — bo geocoder pisze do cache)
        with get_conn() as conn:
            buildings = conn.execute(f"""
                SELECT offer_id, building_name, subdistrict
                FROM listings
                WHERE building_name IS NOT NULL
                  AND building_name != ''
                  AND (geocode_confidence IS NULL OR geocode_confidence < 0.7)
                  {ac_filter} {active_filter}
            """, params).fetchall()

        # Mała optymalizacja: jeden building_name pojawia się N razy. Geocode raz, użyj wielokrotnie.
        seen: dict[str, tuple] = {}
        attempted = 0
        fallback_used = 0
        for row in buildings:
            bname = row["building_name"]
            if bname in seen:
                lat, lon, conf = seen[bname]
            else:
                if attempted >= geocode_budget:
                    break
                query = f"{bname}, Warszawa"
                building_attempts += 1
                attempted += 1
                res = primary.resolve(query)
                # Fallback gdy GUGiK nie zna POI (nazwy własne budynków)
                if (res.latitude is None or res.confidence < 0.5) and fallback is not None:
                    res2 = fallback.resolve(query)
                    if res2.latitude is not None and res2.confidence >= res.confidence:
                        res = res2
                        fallback_used += 1
                lat, lon, conf = res.latitude, res.longitude, res.confidence
                seen[bname] = (lat, lon, conf)

            if lat is None or conf < 0.5:
                building_misses += 1
                continue
            if not dry:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE listings SET latitude=?, longitude=?, geocode_confidence=? WHERE offer_id=?",
                        (lat, lon, conf, row["offer_id"]),
                    )
            geocoded_high += 1

        result.records_updated = dnorm_set + centroid_set + geocoded_high
        result.extras.update({
            "dnorm_set": dnorm_set,
            "centroid_set": centroid_set,
            "geocoded_high": geocoded_high,
            "building_attempts": building_attempts,
            "building_misses": building_misses,
            "fallback_used": fallback_used,
            "dry_run": dry,
        })
        return result
