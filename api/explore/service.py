"""Read-only exposure traversal (FR-13 to FR-16).

Bounded 2-hop BFS over CONNECTED_TO / HAS_ROLE_ON from a party, loan, or
property anchor. Before expanding through any node its degree is checked
(FR-14); parties in the result set are annotated with flag references to
active signals (FR-15). This path performs no writes and triggers no rule
evaluation (FR-16) — everything goes through execute_read.
"""

from collections import defaultdict

from neo4j import ManagedTransaction

from api.config import Settings
from api.explore.models import (
    ExploreEdge,
    ExploreNode,
    ExploreResult,
    GuardMarker,
    SignalFlag,
)
from api.graph import GraphClient
from api.normalize import _base_normalize, normalize_address, normalize_entity_name

MAX_HOPS = 2

# Party-node internals that are not for display
_HIDDEN_PARTY_PROPS = {"embedding"}

_LABEL_FIELDS = {
    "Party": "displayName",
    "Property": "rawAddress",
    "Loan": "id",
}


class ExploreService:
    def __init__(self, graph: GraphClient, settings: Settings) -> None:
        self._graph = graph
        self._settings = settings

    def explore(self, anchor_type: str, query: str) -> ExploreResult | None:
        anchor = self._find_anchor(anchor_type, query)
        if anchor is None:
            return None

        nodes: dict[str, ExploreNode] = {anchor.id: anchor}
        edges: dict[tuple, ExploreEdge] = {}
        guards: list[GuardMarker] = []
        frontier: dict[str, list[str]] = {anchor.nodeType: [anchor.id]}

        for hop in range(1, MAX_HOPS + 1):
            expandable = self._apply_degree_guard(frontier, nodes, guards)
            if not any(expandable.values()):
                break
            next_frontier: dict[str, list[str]] = defaultdict(list)
            for label, ids in expandable.items():
                if not ids:
                    continue
                for row in self._expand(label, ids):
                    neighbor_id = row["neighborId"]
                    if neighbor_id not in nodes:
                        nodes[neighbor_id] = ExploreNode(
                            id=neighbor_id,
                            nodeType=row["neighborLabel"],
                            label=str(
                                row["neighborProps"].get(
                                    _LABEL_FIELDS[row["neighborLabel"]], neighbor_id
                                )
                            ),
                            hop=hop,
                            properties=_display_props(row["neighborProps"]),
                        )
                        next_frontier[row["neighborLabel"]].append(neighbor_id)
                    edge = _to_edge(row, from_label=label)
                    edges.setdefault(
                        (edge.source, edge.target, edge.type, edge.role), edge
                    )
            frontier = dict(next_frontier)

        party_ids = [n.id for n in nodes.values() if n.nodeType == "Party"]
        self._attach_resolution_tiers(party_ids, nodes)
        return ExploreResult(
            anchor=anchor,
            nodes=list(nodes.values()),
            edges=list(edges.values()),
            guards=guards,
            flags=self._signal_flags(party_ids),
        )

    # -- anchor ------------------------------------------------------------

    def _find_anchor(self, anchor_type: str, query: str) -> ExploreNode | None:
        if anchor_type == "party":
            name_forms = list(
                {_base_normalize(query), normalize_entity_name(query)}
            )
            record = self._graph.execute_read(
                lambda tx: tx.run(
                    "MATCH (p:Party) WHERE p.id = $q OR p.normalizedName IN $names "
                    "RETURN p.id AS id, properties(p) AS props "
                    "ORDER BY p.createdAt LIMIT 1",
                    q=query,
                    names=name_forms,
                ).single()
            )
            label_key = "Party"
        elif anchor_type == "loan":
            record = self._graph.execute_read(
                lambda tx: tx.run(
                    "MATCH (l:Loan {id: $q}) RETURN l.id AS id, properties(l) AS props",
                    q=query,
                ).single()
            )
            label_key = "Loan"
        elif anchor_type == "property":
            record = self._graph.execute_read(
                lambda tx: tx.run(
                    "MATCH (p:Property) WHERE p.id IN $forms "
                    "RETURN p.id AS id, properties(p) AS props LIMIT 1",
                    forms=[query, normalize_address(query)],
                ).single()
            )
            label_key = "Property"
        else:
            raise ValueError(f"unknown anchor type {anchor_type!r}")

        if record is None:
            return None
        props = record["props"]
        return ExploreNode(
            id=record["id"],
            nodeType=label_key,
            label=str(props.get(_LABEL_FIELDS[label_key], record["id"])),
            hop=0,
            properties=_display_props(props),
        )

    # -- traversal ---------------------------------------------------------

    def _apply_degree_guard(
        self,
        frontier: dict[str, list[str]],
        nodes: dict[str, ExploreNode],
        guards: list[GuardMarker],
    ) -> dict[str, list[str]]:
        """FR-14: check relationship count before expanding through a node."""
        threshold = self._settings.degree_guard_threshold
        expandable: dict[str, list[str]] = {}
        for label, ids in frontier.items():
            if not ids:
                continue
            degrees = self._graph.execute_read(
                lambda tx, label=label, ids=ids: {
                    r["id"]: r["degree"]
                    for r in tx.run(
                        f"MATCH (n:{label}) WHERE n.id IN $ids "
                        "RETURN n.id AS id, COUNT { (n)--() } AS degree",
                        ids=ids,
                    )
                }
            )
            keep = []
            for node_id in ids:
                degree = degrees.get(node_id, 0)
                if degree > threshold:
                    node = nodes[node_id]
                    guards.append(
                        GuardMarker(
                            nodeId=node_id,
                            nodeType=node.nodeType,
                            label=node.label,
                            degree=degree,
                        )
                    )
                else:
                    keep.append(node_id)
            expandable[label] = keep
        return expandable

    def _expand(self, label: str, ids: list[str]) -> list[dict]:
        def query(tx: ManagedTransaction) -> list[dict]:
            return [
                dict(r)
                for r in tx.run(
                    f"MATCH (n:{label}) WHERE n.id IN $ids "
                    "MATCH (n)-[e:CONNECTED_TO|HAS_ROLE_ON]-(m) "
                    "RETURN n.id AS fromId, type(e) AS edgeType, "
                    "properties(e) AS edgeProps, m.id AS neighborId, "
                    "labels(m)[0] AS neighborLabel, properties(m) AS neighborProps",
                    ids=ids,
                )
            ]

        return self._graph.execute_read(query)

    # -- annotations ---------------------------------------------------------

    def _attach_resolution_tiers(
        self, party_ids: list[str], nodes: dict[str, ExploreNode]
    ) -> None:
        """FR-23: parties expose the match tiers that assembled them."""
        if not party_ids:
            return
        tiers = self._graph.execute_read(
            lambda tx: {
                r["id"]: r["tiers"]
                for r in tx.run(
                    "MATCH (p:Party) WHERE p.id IN $ids "
                    "OPTIONAL MATCH (:RawRecord)-[rt:RESOLVES_TO]->(p) "
                    "RETURN p.id AS id, collect(DISTINCT rt.tier) AS tiers",
                    ids=party_ids,
                )
            }
        )
        for party_id, party_tiers in tiers.items():
            nodes[party_id].properties["resolutionTiers"] = sorted(
                t for t in party_tiers if t
            )

    def _signal_flags(self, party_ids: list[str]) -> list[SignalFlag]:
        """FR-15: signal id and pattern type only — no detail on this path."""
        if not party_ids:
            return []
        return self._graph.execute_read(
            lambda tx: [
                SignalFlag(**dict(r))
                for r in tx.run(
                    "MATCH (s:Signal {status: 'RAISED'}) UNWIND $ids AS pid "
                    "WITH s, pid WHERE pid IN s.relatedPartyIds "
                    "RETURN pid AS partyId, s.id AS signalId, s.patternType AS patternType",
                    ids=party_ids,
                )
            ]
        )


def _display_props(props: dict) -> dict:
    return {k: v for k, v in props.items() if k not in _HIDDEN_PARTY_PROPS}


def _to_edge(row: dict, from_label: str) -> ExploreEdge:
    """Graph edges always originate at the Party end; expansion is
    undirected, so orient by which side is the Party."""
    edge_props = row["edgeProps"]
    if from_label == "Party":
        source, target = row["fromId"], row["neighborId"]
    else:
        source, target = row["neighborId"], row["fromId"]
    return ExploreEdge(
        source=source,
        target=target,
        type=row["edgeType"],
        role=edge_props.get("role"),
        tier=edge_props.get("tier"),
        edgeSource=edge_props.get("source"),
        sourceSystem=edge_props.get("sourceSystem"),
        eventId=edge_props.get("eventId"),
    )
