"""
collectors — source-agnostic framework dla danych wchodzących do platformy.

Trzy rodzaje (kind):
  - 'listings'      — scrapery ofert (otodom_office, otodom_residential, ...)
  - 'transactions'  — granularne dane transakcyjne (RCN, Geoportal WFS, CSV, XLSX)
  - 'aggregates'    — agregaty (NBP, GUS, raporty kwartalne) → transaction_market_snapshots

Każdy collector implementuje Collector ABC z collectors.base. Rejestracja przez
collectors.registry (auto-discovery podmodułów).

CLI:
  python -m collectors list
  python -m collectors run <source> [opcje source-specific]
"""

from .base import Collector, CollectorResult, RawRecord
from .registry import all_collectors, get_collector, register

__all__ = [
    "Collector", "CollectorResult", "RawRecord",
    "all_collectors", "get_collector", "register",
]
