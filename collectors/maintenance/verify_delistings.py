"""
collectors.maintenance.verify_delistings — weryfikuje delisted oferty pod ich URL-em.

Definitywny test (nie heurystyka): pobiera URL każdej delisted oferty.
  HTTP 410/404      → oferta faktycznie usunięta → zostaje delisted (potwierdzone)
  HTTP 200 (żywa)   → fałszywy delisting → przywraca do ACTIVE
  błąd sieci/timeout → pozostawia bez zmian (niepewne)

Eliminuje fałszywe delisty z luk pokrycia scrape'a (oferta zgubiona przez nasz
scraper, ale dalej żywa na portalu).
"""

from __future__ import annotations

import argparse
import ssl
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

from collectors.base import Collector, CollectorResult
from collectors.registry import register

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# strony "oferta nieaktywna" zwracane z HTTP 200
_GONE_MARKERS = ["to ogłoszenie się zakończyło", "nie jest już dostępne",
                 "ogłoszenie nieaktywne", "ogłoszenie wygasło", "zostało usunięte"]


def probe_url(url: str) -> str:
    """Zwraca 'gone' | 'active' | 'unknown'."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        r = urllib.request.urlopen(req, timeout=15, context=_CTX)
        body = r.read(12000).decode("utf-8", errors="replace").lower()
        if any(m in body for m in _GONE_MARKERS):
            return "gone"
        return "active"
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return "gone"
        return "unknown"
    except Exception:
        return "unknown"


@register
class VerifyDelistings(Collector):
    source = "verify_delistings"
    kind = "maintenance"
    schema_version = 1
    description = "Weryfikuje delisted oferty pod URL (410/404=gone, 200=żywa→restore)"

    @classmethod
    def add_cli_args(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--asset-class", default="all",
                            choices=["all", "office", "residential"])
        parser.add_argument("--limit", type=int, default=1000)
        parser.add_argument("--delay", type=float, default=0.6)
        parser.add_argument("--dry-run", action="store_true")

    def run(self, **kwargs) -> CollectorResult:
        from database import get_conn
        result = CollectorResult(source=self.source, kind="maintenance")
        dry = kwargs.get("dry_run", False)
        delay = float(kwargs.get("delay", 0.6))

        ac_filter = ""
        if kwargs["asset_class"] != "all":
            ac_filter = f"AND asset_class='{kwargs['asset_class']}'"

        with get_conn() as conn:
            rows = conn.execute(f"""
                SELECT offer_id, url FROM listings
                WHERE delisted_date IS NOT NULL {ac_filter}
                ORDER BY delisted_date DESC LIMIT {int(kwargs['limit'])}
            """).fetchall()

        result.records_in = len(rows)
        gone = restored = unknown = 0
        for r in rows:
            status = probe_url(r["url"])
            if status == "active":
                restored += 1
                if not dry:
                    with get_conn() as conn:
                        conn.execute("""
                            UPDATE listings SET is_active=1, delisted_date=NULL,
                                listing_status='ACTIVE' WHERE offer_id=?
                        """, (r["offer_id"],))
                        conn.execute("DELETE FROM listing_lifecycle_events "
                                     "WHERE offer_id=? AND event_type='DELISTED'", (r["offer_id"],))
            elif status == "gone":
                gone += 1
            else:
                unknown += 1
            time.sleep(delay)

        result.records_updated = restored
        result.extras.update({"gone_confirmed": gone, "restored_active": restored,
                              "unknown": unknown})
        return result
