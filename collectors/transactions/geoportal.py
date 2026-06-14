"""
collectors.transactions.geoportal — generyczny klient OGC WFS dla usług Geoportal.

Stan na 2026: Krajowa Integracja Ewidencji Gruntów (KIEG) udostępnia działki,
budynki, obręby — ale ŻADNYCH warstw cenowych/transakcyjnych. Warstwy RCN
są per-powiat i większość starostw ich nie publikuje przez WFS.

Ten collector:
  1. `--discover` — odpyta GetCapabilities i wylistuje dostępne warstwy,
     raportując brak warstw transakcyjnych jako warning (nie error).
  2. `--layer X` — pobierze GetFeature dla wskazanej warstwy (gdy w przyszłości
     jakiś urząd opublikuje warstwę cenową) i zmapuje pola wg --mapping.

Architektura source-agnostic: jeżeli pojawi się WFS z transakcjami, wystarczy
config JSON — zero zmian w analytics.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request

from collectors.base import Collector, CollectorResult
from collectors.registry import register
from collectors.transactions._tabular import ImportConfig, import_rows


DEFAULT_WFS = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"
TIMEOUT_S = 30

# Słowa kluczowe wskazujące na warstwę transakcyjną/cenową
PRICE_LAYER_KEYWORDS = ["cen", "rcn", "transak", "wartos", "rciwn"]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OceanPlazaMI/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read()


def discover_layers(base_url: str) -> list[dict]:
    """GetCapabilities → lista warstw [{name, title, is_price_layer}]."""
    sep = "&" if "?" in base_url else "?"
    url = f"{base_url}{sep}SERVICE=WFS&REQUEST=GetCapabilities"
    try:
        body = _get(url).decode("utf-8", errors="replace")
    except Exception:
        # Spróbuj WMS jeśli WFS nie odpowiada
        url = f"{base_url}{sep}SERVICE=WMS&REQUEST=GetCapabilities"
        body = _get(url).decode("utf-8", errors="replace")

    layers = []
    for m in re.finditer(r"<(?:FeatureType|Layer)[^>]*>.*?<Name>([^<]+)</Name>(?:.*?<Title>([^<]*)</Title>)?", body, re.DOTALL):
        name = m.group(1).strip()
        title = (m.group(2) or "").strip()
        text = f"{name} {title}".lower()
        is_price = any(kw in text for kw in PRICE_LAYER_KEYWORDS)
        layers.append({"name": name, "title": title, "is_price_layer": is_price})
    return layers


def fetch_features(base_url: str, layer: str, bbox: str | None = None,
                   max_features: int = 5000) -> list[dict]:
    """WFS GetFeature → lista płaskich dictów properties (GeoJSON)."""
    sep = "&" if "?" in base_url else "?"
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": layer,
        "OUTPUTFORMAT": "application/json",
        "COUNT": str(max_features),
    }
    if bbox:
        params["BBOX"] = bbox
    url = f"{base_url}{sep}{urllib.parse.urlencode(params)}"
    body = _get(url)
    payload = json.loads(body)
    out = []
    for feat in payload.get("features", []):
        props = dict(feat.get("properties") or {})
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Point":
            coords = geom.get("coordinates") or [None, None]
            props["_lon"], props["_lat"] = coords[0], coords[1]
        out.append(props)
    return out


@register
class GeoportalWfsCollector(Collector):
    source = "geoportal_wfs"
    kind = "transactions"
    schema_version = 1
    description = "Generic OGC WFS client (discovery + GetFeature → transactions)"

    @classmethod
    def add_cli_args(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--url", default=DEFAULT_WFS,
                            help=f"Endpoint WFS (domyślnie KIEG: {DEFAULT_WFS})")
        parser.add_argument("--discover", action="store_true",
                            help="Tylko wylistuj warstwy (GetCapabilities)")
        parser.add_argument("--layer", default=None,
                            help="Nazwa warstwy do pobrania (GetFeature)")
        parser.add_argument("--bbox", default=None,
                            help="BBOX filtr: minx,miny,maxx,maxy,EPSG:4326")
        parser.add_argument("--mapping", default=None,
                            help="JSON mapping (jak csv_import) — wymagany przy --layer")
        parser.add_argument("--max-features", type=int, default=5000)
        parser.add_argument("--dry-run", action="store_true")

    def run(self, **kwargs) -> CollectorResult:
        result = CollectorResult(source=self.source, kind="transactions")
        base_url = kwargs["url"]
        result.extras["url_scraped"] = base_url

        # Tryb discovery
        if kwargs.get("discover") or not kwargs.get("layer"):
            try:
                layers = discover_layers(base_url)
            except Exception as e:
                result.status = "error"
                result.error_msg = f"GetCapabilities failed: {e}"
                return result

            price_layers = [l for l in layers if l["is_price_layer"]]
            result.extras["layers_found"] = len(layers)
            result.extras["price_layers"] = [l["name"] for l in price_layers]
            print(f"\n[geoportal] Warstwy dostępne ({len(layers)}):")
            for l in layers:
                marker = " ◀ CENOWA?" if l["is_price_layer"] else ""
                print(f"  - {l['name']}  {l['title']}{marker}")
            if not price_layers:
                print("\n[geoportal] WARNING: brak warstw transakcyjnych/cenowych "
                      "w tym endpoincie. To oczekiwane dla KIEG — pełen RCN wymaga "
                      "wniosku do starostwa (zobacz docs/RCN_ACCESS.md).")
                result.status = "ok"
                result.error_msg = "no price layers available (expected for KIEG)"
            return result

        # Tryb pobierania
        if not kwargs.get("mapping"):
            result.status = "error"
            result.error_msg = "--mapping wymagany przy --layer"
            return result

        cfg = ImportConfig.from_file(kwargs["mapping"])
        result.source = cfg.source
        try:
            feats = fetch_features(
                base_url, kwargs["layer"], kwargs.get("bbox"),
                int(kwargs.get("max_features", 5000)),
            )
        except Exception as e:
            result.status = "error"
            result.error_msg = f"GetFeature failed: {e}"
            return result

        import_rows(iter(feats), cfg, result, dry_run=kwargs.get("dry_run", False))
        return result
