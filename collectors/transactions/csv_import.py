"""
collectors.transactions.csv_import — generyczny import CSV → transactions.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from collectors.base import Collector, CollectorResult
from collectors.registry import register
from collectors.transactions._tabular import ImportConfig, import_rows


@register
class CsvTransactionCollector(Collector):
    source = "csv_import"
    kind = "transactions"
    schema_version = 1
    description = "Generic CSV → transactions (JSON mapping)"

    @classmethod
    def add_cli_args(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--file", required=True, help="Plik CSV")
        parser.add_argument("--mapping", required=True, help="JSON z konfigiem importu")
        parser.add_argument("--dry-run", action="store_true",
                            help="Tylko walidacja, nic nie zapisuje")

    def run(self, **kwargs) -> CollectorResult:
        cfg = ImportConfig.from_file(kwargs["mapping"])
        # mapping definiuje swój `source` — używamy go jako stabilnego ID
        result = CollectorResult(source=cfg.source, kind="transactions")
        result.extras["url_scraped"] = str(Path(kwargs["file"]).resolve())

        try:
            with open(kwargs["file"], "r", encoding=cfg.encoding, newline="") as f:
                for _ in range(cfg.skip_rows):
                    next(f, None)
                reader = csv.DictReader(f, delimiter=cfg.delimiter)
                import_rows(reader, cfg, result, dry_run=kwargs.get("dry_run", False))
        except FileNotFoundError as e:
            result.status = "error"
            result.error_msg = f"file not found: {e}"
        except Exception as e:
            result.status = "error"
            result.error_msg = str(e)

        return result
