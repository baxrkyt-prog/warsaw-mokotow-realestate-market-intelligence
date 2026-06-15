"""
collectors.maintenance.backfill_lifecycle — odtwarza historię lifecycle z istniejących
danych (snapshots + listings). Idempotentny (eventy mają UNIQUE, listingi UPDATE).

Dla każdej oferty:
  - LISTING_CREATED  @ first_seen
  - PRICE_REDUCED / PRICE_INCREASED  z różnic cen między kolejnymi snapshotami
  - DELISTED  @ last_seen  (gdy is_active=0)
Ustawia na listings: listing_status, delisted_date, last_known_price(_per_m2).
"""

from __future__ import annotations

import argparse

from collectors.base import Collector, CollectorResult
from collectors.registry import register


@register
class LifecycleBackfill(Collector):
    source = "backfill_lifecycle"
    kind = "maintenance"
    schema_version = 1
    description = "Odtwarza eventy lifecycle + listing_status ze snapshotów"

    @classmethod
    def add_cli_args(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true")

    def run(self, **kwargs) -> CollectorResult:
        from database import get_conn, insert_lifecycle_event
        result = CollectorResult(source=self.source, kind="maintenance")
        dry = kwargs.get("dry_run", False)

        events = 0
        status_set = 0

        with get_conn() as conn:
            listings = conn.execute("""
                SELECT offer_id, first_seen, last_seen, is_active,
                       price_total, price_per_m2
                FROM listings
            """).fetchall()
            result.records_in = len(listings)

            for L in listings:
                oid = L["offer_id"]

                # 1) LISTING_CREATED @ first_seen
                if L["first_seen"] and not dry:
                    insert_lifecycle_event(conn, oid, L["first_seen"][:19],
                                           "LISTING_CREATED", None, L["price_total"])
                    events += 1

                # 2) Price changes z kolejnych snapshotów (aktywnych, z ceną)
                snaps = conn.execute("""
                    SELECT scrape_date, current_price
                    FROM snapshots
                    WHERE offer_id=? AND active_status=1 AND current_price IS NOT NULL
                    ORDER BY scrape_date
                """, (oid,)).fetchall()
                prev_price = None
                last_price = L["price_total"]
                last_price_m2 = L["price_per_m2"]
                for s in snaps:
                    cur = s["current_price"]
                    if prev_price is not None and cur is not None and abs(cur - prev_price) > 1:
                        etype = "PRICE_REDUCED" if cur < prev_price else "PRICE_INCREASED"
                        if not dry:
                            insert_lifecycle_event(conn, oid, s["scrape_date"], etype,
                                                   prev_price, cur)
                            events += 1
                    prev_price = cur
                    last_price = cur if cur is not None else last_price

                # 3) Status + delisting
                if L["is_active"] == 0:
                    delisted = (L["last_seen"] or "")[:19]
                    if not dry:
                        insert_lifecycle_event(conn, oid, delisted, "DELISTED",
                                               last_price, None)
                        events += 1
                        conn.execute("""
                            UPDATE listings SET
                                listing_status='DELISTED',
                                delisted_date=?,
                                last_known_price=?,
                                last_known_price_per_m2=?
                            WHERE offer_id=?
                        """, (delisted, last_price, last_price_m2, oid))
                        status_set += 1
                else:
                    # status aktywny: doprecyzuj ostatnią zmianą ceny jeśli była
                    status = "ACTIVE"
                    if prev_price is not None and len(snaps) >= 2:
                        first_p = snaps[0]["current_price"]
                        if first_p and last_price and abs(last_price - first_p) > 1:
                            status = "PRICE_REDUCED" if last_price < first_p else "PRICE_INCREASED"
                    if not dry:
                        conn.execute(
                            "UPDATE listings SET listing_status=? WHERE offer_id=?",
                            (status, oid))
                        status_set += 1

        result.records_new = events
        result.records_updated = status_set
        result.extras["events_created"] = events
        result.extras["statuses_set"] = status_set
        return result
