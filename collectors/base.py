"""
collectors/base.py — Collector ABC + DTO.

Każdy konkretny collector dziedziczy po Collector i implementuje co najmniej:
  - kind: Literal['listings','transactions','aggregates']
  - source: str (stabilny identyfikator)
  - run(**kwargs) -> CollectorResult

run() zwraca CollectorResult ze statystykami i zapisuje wynik do DB
(transakcje/agregaty/oferty) plus loguje run do ingestion_runs.
"""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


RawRecord = dict[str, Any]


@dataclass
class CollectorResult:
    source: str
    kind: str
    records_in: int = 0
    records_new: int = 0
    records_updated: int = 0
    records_rejected: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    status: str = "ok"
    error_msg: str | None = None
    duration_ms: int = 0
    extras: dict[str, Any] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.records_rejected += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1

    def to_ingestion_log(self) -> dict[str, Any]:
        return {
            "run_ts": datetime.now(timezone.utc).isoformat(),
            "kind": self.kind,
            "source": self.source,
            "asset_class": self.extras.get("asset_class"),
            "property_type": self.extras.get("property_type"),
            "url_scraped": self.extras.get("url_scraped"),
            "records_in": self.records_in,
            "records_new": self.records_new,
            "records_updated": self.records_updated,
            "records_rejected": self.records_rejected,
            "delisted": None,
            "price_changes": None,
            "status": self.status,
            "error_msg": self.error_msg,
            "duration_ms": self.duration_ms,
        }


class Collector(ABC):
    """Abstrakcyjny kontrakt collectora. Konkretne klasy rejestrują się
    przez @register w submoduŁach lub przez registry.discover()."""

    source: str = ""
    kind: Literal["listings", "transactions", "aggregates", "maintenance"] = "transactions"
    schema_version: int = 1
    description: str = ""

    @classmethod
    @abstractmethod
    def add_cli_args(cls, parser: argparse.ArgumentParser) -> None:
        """Każdy collector deklaruje swoje argumenty (np. --file, --mapping, --since)."""

    @abstractmethod
    def run(self, **kwargs: Any) -> CollectorResult:
        """Główne entry point: wykonaj pobieranie/import i zwróć statystyki."""

    def log_to_ingestion(self, result: CollectorResult) -> None:
        """Wspólny zapis do ingestion_runs — używany przez wszystkich konkretnych collectorów."""
        from database import get_conn, log_run
        with get_conn() as conn:
            log_run(conn, result.to_ingestion_log())
