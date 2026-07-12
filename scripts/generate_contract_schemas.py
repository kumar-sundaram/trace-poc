"""Regenerate the outbound contract JSON Schemas (§9 deliverable).

Usage: uv run python scripts/generate_contract_schemas.py
A test asserts the committed files match the models, so run this after any
contract change.
"""

import json
from pathlib import Path

from api.emitter.contracts import (
    EventEnvelope,
    ResolutionOutcomePayload,
    SignalPayload,
)
from api.ingestion.models import PartyEvent

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "docs" / "contracts"

SCHEMAS = {
    "ingestion-request.schema.json": PartyEvent,
    "event-envelope.schema.json": EventEnvelope,
    "resolution-outcome-payload.schema.json": ResolutionOutcomePayload,
    "signal-payload.schema.json": SignalPayload,
}


def main() -> None:
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMAS.items():
        path = CONTRACTS_DIR / filename
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
