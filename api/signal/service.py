"""Attribute fan-out rule (FR-17) and signal lifecycle (FR-18, FR-19, FR-21).

Runs as a post-write hook after each resolution (scoped to the attribute the
event touched) and on demand across the full graph. A fired rule creates a
Signal node and emits a signal event. Signals advise, humans decide (§5.3).
"""

import hashlib
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from neo4j import ManagedTransaction

from api.config import Settings
from api.emitter.contracts import SignalPayload
from api.emitter.emitter import EventEmitter
from api.graph import GraphClient
from api.ingestion.models import PartyEvent

logger = logging.getLogger(__name__)

PATTERN_ATTRIBUTE_FANOUT = "attribute_fanout"


class SignalService:
    def __init__(self, graph: GraphClient, settings: Settings, emitter: EventEmitter) -> None:
        self._graph = graph
        self._settings = settings
        self._emitter = emitter

    # -- entry points ------------------------------------------------------

    def evaluate_event(self, event: PartyEvent, party_id: str) -> None:
        """Post-write hook (FR-18): only the attribute this event touched can
        have changed, so evaluation is scoped to it."""
        if not event.normalized_address:
            return
        self._evaluate_attribute(
            property_id=event.normalized_address,
            source_system=event.sourceSystem,
            causation_event_id=event.eventId,
        )

    def evaluate_all(self) -> dict:
        """Admin re-run against the full graph (FR-18)."""
        run_id = f"rerun-{uuid4()}"
        min_parties = self._settings.signal.fanout_min_parties

        def candidates(tx: ManagedTransaction) -> list[str]:
            return [
                r["id"]
                for r in tx.run(
                    "MATCH (prop:Property)<-[c:CONNECTED_TO {source: 'shared_attribute'}]"
                    "-(p:Party) "
                    "WITH prop, count(DISTINCT p) AS parties "
                    "WHERE parties >= $min RETURN prop.id AS id",
                    min=min_parties,
                )
            ]

        property_ids = self._graph.execute_read(candidates)
        raised = sum(
            1
            for property_id in property_ids
            if self._evaluate_attribute(
                property_id=property_id,
                source_system="platform_admin",
                causation_event_id=run_id,
            )
        )
        return {"evaluatedAttributes": len(property_ids), "raised": raised, "runId": run_id}

    # -- rule --------------------------------------------------------------

    def _evaluate_attribute(
        self, property_id: str, source_system: str, causation_event_id: str
    ) -> SignalPayload | None:
        signal_cfg = self._settings.signal

        # FR-21: the degree guard applies to rule evaluation.
        degree = self._graph.execute_read(
            lambda tx: tx.run(
                "MATCH (prop:Property {id: $id}) RETURN COUNT { (prop)--() } AS degree",
                id=property_id,
            ).single()["degree"]
        )
        if degree > self._settings.degree_guard_threshold:
            logger.warning(
                "excluded-common-attribute: %r degree=%d exceeds guard threshold %d",
                property_id, degree, self._settings.degree_guard_threshold,
            )
            # An attribute this common is not a meaningful pattern basis.
            # Signals raised while it was still below the guard are
            # reclassified, not deleted — the audit trail survives.
            self._graph.execute_write(
                lambda tx: tx.run(
                    "MATCH (s:Signal {attributeId: $id, status: 'RAISED'}) "
                    "SET s.status = 'EXCLUDED_DEGREE_GUARD'",
                    id=property_id,
                )
            )
            return None

        def loans(tx: ManagedTransaction) -> list[dict]:
            return [
                dict(r)
                for r in tx.run(
                    "MATCH (prop:Property {id: $id})"
                    "<-[:CONNECTED_TO {source: 'shared_attribute'}]-(p:Party)"
                    "-[:HAS_ROLE_ON]->(l:Loan) "
                    "RETURN p.id AS partyId, l.id AS loanRef, l.originatedAt AS originatedAt",
                    id=property_id,
                )
            ]

        rows = self._graph.execute_read(loans)
        if not rows:
            return None

        # FR-17: N+ distinct parties whose loans (any role) originated within
        # the window. Anchor on the newest origination among the group.
        anchor = max(datetime.fromisoformat(r["originatedAt"]) for r in rows)
        window_start = anchor - timedelta(days=signal_cfg.fanout_window_days)
        in_window = [
            r for r in rows if datetime.fromisoformat(r["originatedAt"]) >= window_start
        ]
        parties = sorted({r["partyId"] for r in in_window})
        if len(parties) < signal_cfg.fanout_min_parties:
            return None

        signal_id = self._signal_id(property_id, parties)
        evidence = [f"Property:{property_id}"] + [
            f"Party:{r['partyId']}->Loan:{r['loanRef']}" for r in in_window
        ]
        severity = "MEDIUM" if len(parties) == signal_cfg.fanout_min_parties else "HIGH"
        payload = SignalPayload(
            signalId=signal_id,
            patternType=PATTERN_ATTRIBUTE_FANOUT,
            relatedPartyIds=parties,
            evidencePath=evidence,
            severity=severity,
            causationEventId=causation_event_id,
        )

        if not self._create_signal_node(payload, property_id):
            return None  # already raised for this exact pattern state (FR-2)
        self._emitter.emit_signal(source_system, causation_event_id, payload)
        logger.info(
            "signal raised: %s on %r (%d parties, %s)",
            signal_id, property_id, len(parties), severity,
        )
        return payload

    @staticmethod
    def _signal_id(property_id: str, party_ids: list[str]) -> str:
        """Deterministic identity per (pattern, attribute): a growing cluster
        is one reviewable fact — parties joining later must not re-fire it."""
        digest = hashlib.sha1(
            f"{PATTERN_ATTRIBUTE_FANOUT}|{property_id}".encode()
        ).hexdigest()[:16]
        return f"sig-{digest}"

    def _create_signal_node(self, payload: SignalPayload, property_id: str) -> bool:
        """FR-19: the Signal node in the graph. Returns False if it already existed."""

        def write(tx: ManagedTransaction) -> bool:
            record = tx.run(
                """
                MERGE (s:Signal {id: $id})
                ON CREATE SET s.patternType = $patternType,
                              s.relatedPartyIds = $relatedPartyIds,
                              s.evidencePath = $evidencePath,
                              s.severity = $severity,
                              s.status = 'RAISED',
                              s.attributeId = $attributeId,
                              s.causationEventId = $causationEventId,
                              s.raisedAt = datetime(),
                              s.justCreated = true
                ON MATCH SET s.justCreated = false
                WITH s, s.justCreated AS created
                SET s.justCreated = null
                RETURN created
                """,
                id=payload.signalId,
                patternType=payload.patternType,
                relatedPartyIds=payload.relatedPartyIds,
                evidencePath=payload.evidencePath,
                severity=payload.severity,
                attributeId=property_id,
                causationEventId=payload.causationEventId,
            ).single()
            return record["created"]

        return self._graph.execute_write(write)
