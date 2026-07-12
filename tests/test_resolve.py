"""Tiered resolve pipeline against the curated planted scenarios (FR-3 to FR-9).

Runs on real Titan embeddings (bedrock_client) because the T3 bands are
calibrated to Titan score space; skipped without AWS credentials.
Each test starts from a wiped graph (clean_graph) so counts are exact.
"""

import json

from tests.data import curated


def post_all(client, rows):
    for row in rows:
        resp = client.post("/events", json=row)
        assert resp.status_code == 202, resp.text
    return rows


def party_ids(graph) -> list[str]:
    return graph.execute_read(
        lambda tx: [r["id"] for r in tx.run("MATCH (p:Party) RETURN p.id AS id")]
    )


def resolves_to(graph, event_id: str) -> dict:
    record = graph.execute_read(
        lambda tx: tx.run(
            "MATCH (:RawRecord {eventId: $eid})-[e:RESOLVES_TO]->(p:Party) "
            "RETURN e.tier AS tier, e.method AS method, e.confidence AS confidence, "
            "p.id AS partyId",
            eid=event_id,
        ).single()
    )
    return dict(record)


def role_edges(graph, party_id: str) -> list[dict]:
    return graph.execute_read(
        lambda tx: [
            dict(r)
            for r in tx.run(
                "MATCH (:Party {id: $id})-[r:HAS_ROLE_ON]->(l:Loan) "
                "RETURN r.role AS role, r.sourceSystem AS sourceSystem, "
                "r.tier AS tier, r.source AS source, r.eventId AS eventId, "
                "l.id AS loanRef",
                id=party_id,
            )
        ]
    )


def outcomes(client) -> list[dict]:
    path = client.streams_dir / "resolution-outcome.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestT2VariantCluster:
    def test_three_variants_one_party(self, clean_graph, bedrock_client):
        rows = post_all(bedrock_client, curated("T2_VARIANT_CLUSTER"))
        assert len(party_ids(clean_graph)) == 1

        # JONATHAN SMITH, same address, different source → deterministic T2
        assert resolves_to(clean_graph, rows[1]["eventId"])["tier"] == "T2"
        # Jon A. Smith → falls through to vector/LLM (§8 step 2: "Tier 2/3")
        assert resolves_to(clean_graph, rows[2]["eventId"])["tier"] in ("T3", "T4")

    def test_cross_source_roles_aggregate(self, clean_graph, bedrock_client):
        """FR-9 / §8 step 4: same person, new role, different sourceSystem →
        role edge lands on the existing party."""
        post_all(bedrock_client, curated("T2_VARIANT_CLUSTER"))
        party = party_ids(clean_graph)[0]
        edges = role_edges(clean_graph, party)
        assert len(edges) == 3
        assert {e["role"] for e in edges} == {"BORROWER", "SPONSOR"}
        assert {e["sourceSystem"] for e in edges} == {
            "LoanSphere_Origination", "ServicingMaster_Pro", "Core_Invest_DB",
        }
        # No untraced edges (§5.3): full provenance on every role edge
        for edge in edges:
            assert edge["sourceSystem"] and edge["eventId"] and edge["tier"] and edge["source"]


class TestIdempotentRedelivery:
    def test_duplicate_event_changes_nothing(self, clean_graph, bedrock_client):
        original = curated("T2_VARIANT_CLUSTER")[:1]
        duplicate = curated("IDEMPOTENCY_DUPLICATE")
        post_all(bedrock_client, original)
        post_all(bedrock_client, duplicate)  # same (sourceSystem, eventId)
        assert len(party_ids(clean_graph)) == 1
        counts = clean_graph.execute_read(
            lambda tx: tx.run(
                "MATCH (r:RawRecord) WITH count(r) AS raws "
                "MATCH ()-[e:RESOLVES_TO]->() WITH raws, count(e) AS links "
                "MATCH ()-[h:HAS_ROLE_ON]->() RETURN raws, links, count(h) AS roles"
            ).single()
        )
        assert counts["raws"] == 1
        assert counts["links"] == 1
        assert counts["roles"] == 1
        assert len(outcomes(bedrock_client)) == 1  # no second outcome event


class TestEntitySuffix:
    def test_llc_variants_one_party_via_t2(self, clean_graph, bedrock_client):
        rows = post_all(bedrock_client, curated("T2_ENTITY_SUFFIX"))
        assert len(party_ids(clean_graph)) == 1
        assert resolves_to(clean_graph, rows[1]["eventId"])["tier"] == "T2"


class TestTier1Ssn:
    def test_same_ssn_different_name_and_address(self, clean_graph, bedrock_client):
        rows = post_all(bedrock_client, curated("TIER1_SSN_MATCH"))
        assert len(party_ids(clean_graph)) == 1
        link = resolves_to(clean_graph, rows[1]["eventId"])
        assert link["tier"] == "T1"
        assert link["confidence"] == 1.0


class TestFuzzyTier34:
    def test_robb_chen_resolves_to_robert_chen(self, clean_graph, bedrock_client):
        rows = post_all(bedrock_client, curated("T3_T4_FUZZY"))
        assert len(party_ids(clean_graph)) == 1
        link = resolves_to(clean_graph, rows[1]["eventId"])
        # Names differ, so T3 auto-match is barred; the LLM judges it
        assert link["tier"] == "T4"
        assert link["method"] == "llm_disambiguation"


class TestPartyTypeIsolation:
    def test_individual_never_merges_with_entity(self, clean_graph, bedrock_client):
        post_all(bedrock_client, curated("PARTY_TYPE_ISOLATION"))
        assert len(party_ids(clean_graph)) == 2


class TestMultiSourceEntity:
    def test_same_entity_two_sources_two_roles(self, clean_graph, bedrock_client):
        post_all(bedrock_client, curated("MULTI_SOURCE_ENTITY_EXPOSURE"))
        ids = party_ids(clean_graph)
        assert len(ids) == 1
        edges = role_edges(clean_graph, ids[0])
        assert {(e["role"], e["sourceSystem"]) for e in edges} == {
            ("PROPERTY_MANAGER", "Core_Invest_DB"),
            ("SPONSOR", "LoanSphere_Origination"),
        }


class TestHighConnectivityNegative:
    def test_patricia_six_loans_one_party(self, clean_graph, bedrock_client):
        post_all(bedrock_client, curated("HIGH_CONNECTIVITY_NEGATIVE"))
        ids = party_ids(clean_graph)
        assert len(ids) == 1
        assert len(role_edges(clean_graph, ids[0])) == 6
        properties = clean_graph.execute_read(
            lambda tx: tx.run(
                "MATCH (:Party {id: $id})-[:CONNECTED_TO]->(prop) RETURN count(prop) AS n",
                id=ids[0],
            ).single()["n"]
        )
        assert properties == 6


class TestAddressLessConfidence:
    def test_sponsor_without_address_capped(self, clean_graph, bedrock_client):
        post_all(bedrock_client, curated("ADDRESS_LESS_CONFIDENCE"))
        [outcome] = outcomes(bedrock_client)
        payload = outcome["payload"]
        assert payload["created"] is True
        assert payload["matchMethod"] == "new_party_name_only"
        # §4.1: the outcome must reflect reduced confidence
        assert payload["confidence"] <= 0.85
        no_property = clean_graph.execute_read(
            lambda tx: tx.run("MATCH ()-[c:CONNECTED_TO]->() RETURN count(c) AS n").single()["n"]
        )
        assert no_property == 0


class TestSharedAttributeShape:
    def test_fanout_parties_stay_distinct_but_share_property(
        self, clean_graph, bedrock_client
    ):
        """FR-12: three LLCs at 777 Risk Avenue → three parties, ONE Property
        node, three shared_attribute edges — never party-to-party edges."""
        post_all(bedrock_client, curated("FANOUT_POSITIVE"))
        assert len(party_ids(clean_graph)) == 3
        shape = clean_graph.execute_read(
            lambda tx: tx.run(
                "MATCH (prop:Property) WITH count(prop) AS props "
                "MATCH ()-[c:CONNECTED_TO]->() "
                "RETURN props, count(c) AS edges, "
                "collect(DISTINCT c.source) AS sources, collect(DISTINCT c.tier) AS tiers"
            ).single()
        )
        assert shape["props"] == 1
        assert shape["edges"] == 3
        assert shape["sources"] == ["shared_attribute"]
        assert shape["tiers"] == ["T4"]

    def test_numbered_registrations_never_merge(self, clean_graph, bedrock_client):
        """Generic Holdings 0/1/2 LLC at one address embed near-identically —
        the name-equality bar plus the digit guard must keep them apart."""
        post_all(bedrock_client, curated("DEGREE_GUARD")[:3])
        assert len(party_ids(clean_graph)) == 3


class TestOutcomeStream:
    def test_every_outcome_correlates_to_its_request(self, clean_graph, bedrock_client):
        rows = post_all(bedrock_client, curated("T2_VARIANT_CLUSTER"))
        emitted = outcomes(bedrock_client)
        assert len(emitted) == 3
        by_event = {o["eventId"]: o for o in emitted}
        for row in rows:
            outcome = by_event[row["eventId"]]
            assert outcome["sourceSystem"] == row["sourceSystem"]
            assert outcome["eventType"] == "resolution-outcome"
        created_flags = [o["payload"]["created"] for o in emitted]
        assert created_flags.count(True) == 1  # only the first creates
        assert len({o["payload"]["masteredPartyId"] for o in emitted}) == 1
