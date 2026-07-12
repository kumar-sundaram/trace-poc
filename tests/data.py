"""Shared access to the CSV fixtures (docs/test-data)."""

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "docs" / "test-data"


def load_rows(filename: str, scenario: str | None = None) -> list[dict]:
    """CSV rows as ingestion payloads: scenario tag stripped, blanks dropped."""
    with open(DATA_DIR / filename) as f:
        return [
            {k: v for k, v in row.items() if k != "scenario" and v}
            for row in csv.DictReader(f)
            if scenario is None or row["scenario"] == scenario
        ]


def curated(scenario: str) -> list[dict]:
    return load_rows("party_network_seed_curated.csv", scenario)
