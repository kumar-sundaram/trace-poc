"""Tiered matching pipeline — chain of responsibility (§5.2).

Each stage either resolves (returns a MatchDecision) or defers to the next
(returns None). All stages exhausted → the caller creates a new party.
Adding a tier is inserting a stage, not rewriting the pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from typing import Literal

from neo4j import ManagedTransaction

from api.config import Settings
from api.graph import VECTOR_INDEX_NAME, GraphClient
from api.ingestion.models import PartyEvent
from api.resolve.ports import EmbeddingClient, Judgment, LLMClient, PartyDescriptor

Tier = Literal["T1", "T2", "T3", "T4"]


@dataclass(frozen=True)
class MatchDecision:
    party_id: str
    tier: Tier
    method: str
    confidence: float
    rationale: str | None = None


@dataclass(frozen=True)
class VectorCandidate:
    party_id: str
    normalized_name: str
    normalized_address: str | None
    score: float


@dataclass
class MatchContext:
    """Carried through the chain; later stages see what earlier ones learned."""

    event: PartyEvent
    graph: GraphClient
    settings: Settings
    embedding_client: EmbeddingClient
    llm_client: LLMClient
    candidates: list[VectorCandidate] = field(default_factory=list)

    @cached_property
    def embedding(self) -> list[float]:
        """FR-5: name + address; name only for address-less parties."""
        text = self.event.normalized_name
        if self.event.normalized_address:
            text = f"{text} {self.event.normalized_address}"
        return self.embedding_client.embed(text)


class MatchStage(ABC):
    @abstractmethod
    def attempt(self, ctx: MatchContext) -> MatchDecision | None: ...


class Tier1ExactIdentifier(MatchStage):
    """FR-3: deterministic match on exact SSN/Tax ID, same party type."""

    def attempt(self, ctx: MatchContext) -> MatchDecision | None:
        if not ctx.event.ssnOrTaxId:
            return None

        def query(tx: ManagedTransaction):
            return tx.run(
                "MATCH (p:Party {partyType: $partyType, ssnOrTaxId: $ssn}) "
                "RETURN p.id AS id LIMIT 1",
                partyType=ctx.event.partyType,
                ssn=ctx.event.ssnOrTaxId,
            ).single()

        record = ctx.graph.execute_read(query)
        if record is None:
            return None
        return MatchDecision(
            party_id=record["id"], tier="T1", method="exact_identifier", confidence=1.0
        )


class Tier2NormalizedNameAddress(MatchStage):
    """FR-4: deterministic match on normalized name + normalized address,
    where the address is a Property the candidate party is connected to."""

    def attempt(self, ctx: MatchContext) -> MatchDecision | None:
        if not ctx.event.normalized_address:
            return None

        def query(tx: ManagedTransaction):
            return tx.run(
                "MATCH (p:Party {partyType: $partyType, normalizedName: $name})"
                "-[:CONNECTED_TO]->(:Property {normalizedAddress: $address}) "
                "RETURN p.id AS id LIMIT 1",
                partyType=ctx.event.partyType,
                name=ctx.event.normalized_name,
                address=ctx.event.normalized_address,
            ).single()

        record = ctx.graph.execute_read(query)
        if record is None:
            return None
        return MatchDecision(
            party_id=record["id"],
            tier="T2",
            method="normalized_name_address",
            confidence=0.99,
        )


class Tier3VectorSimilarity(MatchStage):
    """FR-5: vector fallback over same-type parties.

    Auto-match requires score >= auto_match_threshold AND exact normalizedName
    equality — near-identical strings with differing names (numbered LLCs at a
    registered-agent address) defer to Tier 4 instead of silently merging.
    Address-less events have scores capped below the auto-match band.
    Candidates above no_match_threshold are left for Tier 4.
    """

    def attempt(self, ctx: MatchContext) -> MatchDecision | None:
        resolve = ctx.settings.resolve
        embedding = ctx.embedding
        addressless = ctx.event.normalized_address is None

        def query(tx: ManagedTransaction):
            result = tx.run(
                f"CALL db.index.vector.queryNodes('{VECTOR_INDEX_NAME}', $k, $embedding) "
                "YIELD node, score "
                "WHERE node.partyType = $partyType "
                "RETURN node.id AS id, node.normalizedName AS name, "
                "node.normalizedAddress AS address, score",
                k=resolve.vector_top_k,
                embedding=embedding,
                partyType=ctx.event.partyType,
            )
            return [
                VectorCandidate(
                    party_id=r["id"],
                    normalized_name=r["name"],
                    normalized_address=r["address"],
                    score=r["score"],
                )
                for r in result
            ]

        candidates = ctx.graph.execute_read(query)
        if addressless:
            cap = resolve.addressless_confidence_cap
            candidates = [
                VectorCandidate(c.party_id, c.normalized_name, c.normalized_address,
                                min(c.score, cap))
                for c in candidates
            ]
        candidates = [c for c in candidates if c.score > resolve.no_match_threshold]
        candidates.sort(key=lambda c: c.score, reverse=True)

        if (
            candidates
            and candidates[0].score >= resolve.auto_match_threshold
            and candidates[0].normalized_name == ctx.event.normalized_name
        ):
            top = candidates[0]
            return MatchDecision(
                party_id=top.party_id,
                tier="T3",
                method="vector_similarity",
                confidence=top.score,
            )

        ctx.candidates = candidates  # ambiguous band → Tier 4
        return None


class Tier4LLMDisambiguation(MatchStage):
    """FR-6: judge each ambiguous candidate; first MATCH wins. NO_MATCH and
    UNCERTAIN both fall through — uncertainty creates a new party, never a
    merge (§5.3)."""

    def attempt(self, ctx: MatchContext) -> MatchDecision | None:
        if not ctx.candidates:
            return None
        incoming = PartyDescriptor(
            party_type=ctx.event.partyType,
            normalized_name=ctx.event.normalized_name,
            normalized_address=ctx.event.normalized_address,
        )
        for candidate in ctx.candidates:
            descriptor = PartyDescriptor(
                party_type=ctx.event.partyType,
                normalized_name=candidate.normalized_name,
                normalized_address=candidate.normalized_address,
            )
            result = ctx.llm_client.disambiguate(incoming, descriptor)
            if result.judgment == Judgment.MATCH:
                return MatchDecision(
                    party_id=candidate.party_id,
                    tier="T4",
                    method="llm_disambiguation",
                    confidence=candidate.score,
                    rationale=result.rationale,
                )
        return None


def default_stages() -> list[MatchStage]:
    return [
        Tier1ExactIdentifier(),
        Tier2NormalizedNameAddress(),
        Tier3VectorSimilarity(),
        Tier4LLMDisambiguation(),
    ]
