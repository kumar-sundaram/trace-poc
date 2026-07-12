"""Outbound event contracts (FR-20) — versioned, published deliverables (§9).

One shared envelope, two type-specific payloads, two streams separated by
data classification: resolution-outcome for data consumers, signal for risk
consumers. The envelope's correlation fields (sourceSystem, eventId) always
identify the originating ingestion event, so consumers of both streams can
reconstruct ordering across them.
"""

from datetime import datetime
from typing import Literal, Union

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0.0"


class ResolutionOutcomePayload(BaseModel):
    """Intended consumer: the originating transactional system and other data
    consumers enriching their records with the mastered party."""

    masteredPartyId: str
    created: bool = Field(description="True if a new Party was created, false if matched")
    matchTier: Literal["T1", "T2", "T3", "T4"] | None = Field(
        default=None, description="Tier that resolved the match; null when a new party was created"
    )
    matchMethod: str
    confidence: float = Field(ge=0.0, le=1.0)
    rawRecordId: str = Field(description="Alias linkage: the raw record preserved by FR-7")
    aliasName: str = Field(description="The name exactly as submitted, preserved as an alias")


class SignalPayload(BaseModel):
    """Intended consumer: risk review. Advisory only — never a gate (§5.3)."""

    signalId: str
    patternType: str
    relatedPartyIds: list[str]
    evidencePath: list[str] = Field(
        description="Ordered node/edge references substantiating the pattern (FR-19)"
    )
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    causationEventId: str = Field(
        description="eventId of the ingestion event whose processing raised this signal"
    )


class EventEnvelope(BaseModel):
    eventType: Literal["resolution-outcome", "signal"]
    schemaVersion: str = SCHEMA_VERSION
    sourceSystem: str = Field(description="Correlation: source system of the originating event")
    eventId: str = Field(description="Correlation: eventId of the originating ingestion event")
    timestamp: datetime
    payload: Union[ResolutionOutcomePayload, SignalPayload]
