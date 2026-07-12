"""Event emitter port and the POC's file-based adapter (FR-20).

Each JSONL file is append-only and stands in for a broker topic. Production
binds a broker adapter behind the same port; the core never knows (§5.2).
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from api.config import Settings
from api.emitter.contracts import (
    EventEnvelope,
    ResolutionOutcomePayload,
    SignalPayload,
)


class EventEmitter(ABC):
    @abstractmethod
    def emit_resolution_outcome(
        self, source_system: str, event_id: str, payload: ResolutionOutcomePayload
    ) -> EventEnvelope: ...

    @abstractmethod
    def emit_signal(
        self, source_system: str, event_id: str, payload: SignalPayload
    ) -> EventEnvelope: ...

    def reset(self) -> None:
        """Clear both streams (demo reset, FR-24). No-op for adapters whose
        downstream cannot be truncated."""


class JsonlEmitter(EventEmitter):
    def __init__(self, settings: Settings) -> None:
        self._outcome_path = settings.streams.resolution_outcome_path
        self._signal_path = settings.streams.signal_path
        self._outcome_path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, path: Path, envelope: EventEnvelope) -> EventEnvelope:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(envelope.model_dump_json() + "\n")
        return envelope

    def emit_resolution_outcome(
        self, source_system: str, event_id: str, payload: ResolutionOutcomePayload
    ) -> EventEnvelope:
        envelope = EventEnvelope(
            eventType="resolution-outcome",
            sourceSystem=source_system,
            eventId=event_id,
            timestamp=datetime.now(UTC),
            payload=payload,
        )
        return self._append(self._outcome_path, envelope)

    def emit_signal(
        self, source_system: str, event_id: str, payload: SignalPayload
    ) -> EventEnvelope:
        envelope = EventEnvelope(
            eventType="signal",
            sourceSystem=source_system,
            eventId=event_id,
            timestamp=datetime.now(UTC),
            payload=payload,
        )
        return self._append(self._signal_path, envelope)

    def reset(self) -> None:
        for path in (self._outcome_path, self._signal_path):
            path.unlink(missing_ok=True)


def build_emitter(settings: Settings) -> EventEmitter:
    return JsonlEmitter(settings)
