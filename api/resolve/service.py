"""Resolution service: the write path from accepted event to committed graph.

Match phase runs read-only (tiers T1–T4, external embedding/LLM calls kept
outside any transaction); the write phase is one ACID transaction (NFR-2)
covering RawRecord, Party (created or enriched), RESOLVES_TO, Property/Loan
nodes and their edges — all with provenance (FR-7, §5.3 no untraced edges).
After commit, the resolution-outcome event is emitted (FR-20) and the
post-write hook (signal evaluation, FR-18) runs.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from neo4j import ManagedTransaction

from api.config import Settings
from api.emitter.contracts import ResolutionOutcomePayload
from api.emitter.emitter import EventEmitter
from api.graph import GraphClient
from api.ingestion.models import PartyEvent
from api.resolve.pipeline import MatchContext, MatchDecision, MatchStage, default_stages
from api.resolve.ports import EmbeddingClient, LLMClient

logger = logging.getLogger(__name__)

PostWriteHook = Callable[[PartyEvent, str], None]


class ResolutionService:
    def __init__(
        self,
        graph: GraphClient,
        settings: Settings,
        embedding_client: EmbeddingClient,
        llm_client: LLMClient,
        emitter: EventEmitter,
        stages: list[MatchStage] | None = None,
        post_write_hook: PostWriteHook | None = None,
    ) -> None:
        self._graph = graph
        self._settings = settings
        self._embedding_client = embedding_client
        self._llm_client = llm_client
        self._emitter = emitter
        self._stages = stages if stages is not None else default_stages()
        self._post_write_hook = post_write_hook

    def is_already_processed(self, event: PartyEvent) -> bool:
        """FR-2: a (sourceSystem, eventId) pair is processed at most once."""

        def check(tx: ManagedTransaction) -> bool:
            record = tx.run(
                "MATCH (r:RawRecord {id: $id}) RETURN count(r) > 0 AS seen",
                id=event.raw_record_id,
            ).single()
            return record["seen"]

        return self._graph.execute_read(check)

    def resolve(self, event: PartyEvent) -> ResolutionOutcomePayload:
        ctx = MatchContext(
            event=event,
            graph=self._graph,
            settings=self._settings,
            embedding_client=self._embedding_client,
            llm_client=self._llm_client,
        )
        decision: MatchDecision | None = None
        for stage in self._stages:
            decision = stage.attempt(ctx)
            if decision is not None:
                break

        if decision is not None:
            party_id = decision.party_id
            confidence = decision.confidence
            method = decision.method
            embedding = None
        else:
            # Fail toward review (§5.3): no confident match → new party.
            party_id = str(uuid4())
            addressless = event.normalized_address is None
            confidence = (
                self._settings.resolve.addressless_confidence_cap if addressless else 1.0
            )
            method = "new_party_name_only" if addressless else "new_party"
            embedding = ctx.embedding  # already computed by Tier 3

        edge_tier = decision.tier if decision else "NEW"
        now = datetime.now(UTC).isoformat()

        def write(tx: ManagedTransaction) -> None:
            self._write_raw_record(tx, event, now)
            if decision is None:
                self._create_party(tx, event, party_id, confidence, embedding, now)
            else:
                self._enrich_party(tx, event, party_id)
            self._link_raw_record(tx, event, party_id, decision, confidence, now)
            if event.normalized_address:
                self._connect_property(tx, event, party_id)
            if event.role:
                self._attach_role(tx, event, party_id, edge_tier, now)

        self._graph.execute_write(write)

        payload = ResolutionOutcomePayload(
            masteredPartyId=party_id,
            created=decision is None,
            matchTier=decision.tier if decision else None,
            matchMethod=method,
            confidence=round(confidence, 4),
            rawRecordId=event.raw_record_id,
            aliasName=event.normalized_name,
        )
        self._emitter.emit_resolution_outcome(event.sourceSystem, event.eventId, payload)
        logger.info(
            "resolved %s -> party %s (%s, %s, %.3f)",
            event.raw_record_id, party_id, edge_tier, method, confidence,
        )
        if self._post_write_hook is not None:
            self._post_write_hook(event, party_id)
        return payload

    @staticmethod
    def _write_raw_record(tx: ManagedTransaction, event: PartyEvent, now: str) -> None:
        """FR-7: no raw record is ever discarded; alias history is preserved."""
        tx.run(
            """
            CREATE (r:RawRecord {
                id: $id, sourceSystem: $sourceSystem, eventId: $eventId,
                partyType: $partyType, firstName: $firstName, lastName: $lastName,
                entityName: $entityName, address: $address, ssnOrTaxId: $ssnOrTaxId,
                role: $role, loanRef: $loanRef, normalizedName: $normalizedName,
                normalizedAddress: $normalizedAddress, receivedAt: $receivedAt
            })
            """,
            id=event.raw_record_id,
            sourceSystem=event.sourceSystem,
            eventId=event.eventId,
            partyType=event.partyType,
            firstName=event.firstName,
            lastName=event.lastName,
            entityName=event.entityName,
            address=event.address,
            ssnOrTaxId=event.ssnOrTaxId,
            role=event.role,
            loanRef=event.loanRef,
            normalizedName=event.normalized_name,
            normalizedAddress=event.normalized_address,
            receivedAt=now,
        )

    @staticmethod
    def _create_party(
        tx: ManagedTransaction,
        event: PartyEvent,
        party_id: str,
        confidence: float,
        embedding: list[float],
        now: str,
    ) -> None:
        tx.run(
            """
            CREATE (p:Party {
                id: $id, partyType: $partyType, displayName: $displayName,
                normalizedName: $normalizedName, normalizedAddress: $normalizedAddress,
                ssnOrTaxId: $ssnOrTaxId, createdAt: $now,
                sourceSystem: $sourceSystem, eventId: $eventId
            })
            WITH p
            CALL db.create.setNodeVectorProperty(p, 'embedding', $embedding)
            RETURN p.id
            """,
            id=party_id,
            partyType=event.partyType,
            displayName=(
                f"{event.firstName} {event.lastName}"
                if event.partyType == "INDIVIDUAL"
                else event.entityName
            ),
            normalizedName=event.normalized_name,
            normalizedAddress=event.normalized_address,
            ssnOrTaxId=event.ssnOrTaxId,
            now=now,
            sourceSystem=event.sourceSystem,
            eventId=event.eventId,
            embedding=embedding,
        )

    @staticmethod
    def _enrich_party(tx: ManagedTransaction, event: PartyEvent, party_id: str) -> None:
        """A matched party gains an identifier it lacked (helps later T1 hits)."""
        if event.ssnOrTaxId:
            tx.run(
                "MATCH (p:Party {id: $id}) "
                "SET p.ssnOrTaxId = coalesce(p.ssnOrTaxId, $ssn)",
                id=party_id,
                ssn=event.ssnOrTaxId,
            )

    @staticmethod
    def _link_raw_record(
        tx: ManagedTransaction,
        event: PartyEvent,
        party_id: str,
        decision: MatchDecision | None,
        confidence: float,
        now: str,
    ) -> None:
        tx.run(
            """
            MATCH (r:RawRecord {id: $rawId}), (p:Party {id: $partyId})
            CREATE (r)-[:RESOLVES_TO {
                tier: $tier, method: $method, confidence: $confidence,
                rationale: $rationale, sourceSystem: $sourceSystem,
                eventId: $eventId, resolvedAt: $now
            }]->(p)
            """,
            rawId=event.raw_record_id,
            partyId=party_id,
            tier=decision.tier if decision else None,
            method=decision.method if decision else "new_party",
            confidence=confidence,
            rationale=decision.rationale if decision else None,
            sourceSystem=event.sourceSystem,
            eventId=event.eventId,
            now=now,
        )

    @staticmethod
    def _connect_property(tx: ManagedTransaction, event: PartyEvent, party_id: str) -> None:
        """FR-12: shared attributes are attribute nodes both parties connect
        to (tier T4, source 'shared_attribute') — never party-to-party edges."""
        tx.run(
            """
            MATCH (p:Party {id: $partyId})
            MERGE (prop:Property {id: $normalizedAddress})
            ON CREATE SET prop.normalizedAddress = $normalizedAddress,
                          prop.rawAddress = $rawAddress
            MERGE (p)-[c:CONNECTED_TO]->(prop)
            ON CREATE SET c.tier = 'T4', c.source = 'shared_attribute',
                          c.sourceSystem = $sourceSystem, c.eventId = $eventId
            """,
            partyId=party_id,
            normalizedAddress=event.normalized_address,
            rawAddress=event.address,
            sourceSystem=event.sourceSystem,
            eventId=event.eventId,
        )

    @staticmethod
    def _attach_role(
        tx: ManagedTransaction, event: PartyEvent, party_id: str, tier: str, now: str
    ) -> None:
        """FR-9/FR-11: role edges accumulate on the mastered party; edge
        identity is (party, loan, role) so re-assertion of the same role
        from any source stays a single edge."""
        tx.run(
            """
            MATCH (p:Party {id: $partyId})
            MERGE (l:Loan {id: $loanRef})
            ON CREATE SET l.originatedAt = $now
            MERGE (p)-[r:HAS_ROLE_ON {role: $role}]->(l)
            ON CREATE SET r.tier = $tier, r.source = 'event_role',
                          r.sourceSystem = $sourceSystem, r.eventId = $eventId
            """,
            partyId=party_id,
            loanRef=event.loanRef,
            role=event.role,
            tier=tier,
            now=now,
            sourceSystem=event.sourceSystem,
            eventId=event.eventId,
        )
