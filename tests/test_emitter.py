"""Emitter and outbound contracts (FR-20)."""

import json
from pathlib import Path

from api.config import Settings
from api.emitter.contracts import (
    SCHEMA_VERSION,
    EventEnvelope,
    ResolutionOutcomePayload,
    SignalPayload,
)
from api.emitter.emitter import JsonlEmitter
from scripts.generate_contract_schemas import CONTRACTS_DIR, SCHEMAS


def _settings_with_streams(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.streams.directory = tmp_path
    return settings


def _outcome_payload() -> ResolutionOutcomePayload:
    return ResolutionOutcomePayload(
        masteredPartyId="party-1",
        created=False,
        matchTier="T2",
        matchMethod="normalized_name_address",
        confidence=0.97,
        rawRecordId="raw-1",
        aliasName="JONATHAN SMITH",
    )


def _signal_payload() -> SignalPayload:
    return SignalPayload(
        signalId="sig-1",
        patternType="attribute_fanout",
        relatedPartyIds=["party-1", "party-2", "party-3"],
        evidencePath=["party-1", "CONNECTED_TO", "property-9"],
        severity="MEDIUM",
        causationEventId="evt-123",
    )


class TestJsonlEmitter:
    def test_streams_are_separate_and_append_only(self, tmp_path):
        emitter = JsonlEmitter(_settings_with_streams(tmp_path))
        emitter.emit_resolution_outcome("LoanSphere_Origination", "evt-1", _outcome_payload())
        emitter.emit_resolution_outcome("LoanSphere_Origination", "evt-2", _outcome_payload())
        emitter.emit_signal("Core_Invest_DB", "evt-123", _signal_payload())

        outcome_lines = (tmp_path / "resolution-outcome.jsonl").read_text().splitlines()
        signal_lines = (tmp_path / "signal.jsonl").read_text().splitlines()
        assert len(outcome_lines) == 2
        assert len(signal_lines) == 1
        assert all(json.loads(line)["eventType"] == "resolution-outcome" for line in outcome_lines)
        assert json.loads(signal_lines[0])["eventType"] == "signal"

    def test_envelope_round_trips_through_contract_model(self, tmp_path):
        emitter = JsonlEmitter(_settings_with_streams(tmp_path))
        emitter.emit_resolution_outcome("ServicingMaster_Pro", "evt-9", _outcome_payload())
        line = (tmp_path / "resolution-outcome.jsonl").read_text().splitlines()[0]
        envelope = EventEnvelope.model_validate_json(line)
        assert envelope.schemaVersion == SCHEMA_VERSION
        assert envelope.sourceSystem == "ServicingMaster_Pro"
        assert envelope.eventId == "evt-9"
        assert envelope.payload.masteredPartyId == "party-1"

    def test_signal_carries_causation_reference(self, tmp_path):
        emitter = JsonlEmitter(_settings_with_streams(tmp_path))
        envelope = emitter.emit_signal("Core_Invest_DB", "evt-123", _signal_payload())
        assert envelope.payload.causationEventId == "evt-123"
        assert envelope.eventId == "evt-123"  # correlation and causation agree


def test_committed_schemas_match_models():
    """The §9 deliverable files must stay in sync with the Pydantic models."""
    for filename, model in SCHEMAS.items():
        committed = json.loads((CONTRACTS_DIR / filename).read_text())
        assert committed == model.model_json_schema(), (
            f"{filename} is stale — run scripts/generate_contract_schemas.py"
        )
