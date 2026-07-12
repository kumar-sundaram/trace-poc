"""Ports for external dependencies of the resolve pipeline (NFR-3, FR-6).

The core pipeline never knows which adapter is bound (§5.2 ports and adapters).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class EmbeddingClient(ABC):
    """Embeds a normalized party string for Tier-3 vector matching (FR-5)."""

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...


class Judgment(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class PartyDescriptor:
    """What Tier-4 disambiguation sees of each record."""

    party_type: str
    normalized_name: str
    normalized_address: str | None


@dataclass(frozen=True)
class DisambiguationResult:
    judgment: Judgment
    rationale: str


class LLMClient(ABC):
    """Tier-4 disambiguator (FR-6): judges an ambiguous candidate pair."""

    @abstractmethod
    def disambiguate(
        self, incoming: PartyDescriptor, candidate: PartyDescriptor
    ) -> DisambiguationResult: ...
