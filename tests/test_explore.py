"""Explore — read-only exposure lookup (FR-13 to FR-16, NFR-5)."""

import time

from tests.data import curated


def post_all(client, rows):
    for row in rows:
        resp = client.post("/events", json=row)
        assert resp.status_code == 202, resp.text


def build_mini_graph(graph):
    """p1 —CONNECTED_TO→ prop ←CONNECTED_TO— p2 —HAS_ROLE_ON→ loan.

    From p1: prop is hop 1, p2 is hop 2, loan is hop 3 (out of bounds)."""
    graph.execute_write(
        lambda tx: tx.run(
            """
            CREATE (p1:Party {id: 'p1', partyType: 'INDIVIDUAL',
                              normalizedName: 'ANNA ONE', displayName: 'Anna One'})
            CREATE (p2:Party {id: 'p2', partyType: 'INDIVIDUAL',
                              normalizedName: 'BEN TWO', displayName: 'Ben Two'})
            CREATE (prop:Property {id: '9 SHARED CT', normalizedAddress: '9 SHARED CT',
                                   rawAddress: '9 Shared Court'})
            CREATE (loan:Loan {id: 'MF-X1', originatedAt: '2026-07-12T00:00:00+00:00'})
            CREATE (p1)-[:CONNECTED_TO {tier: 'T4', source: 'shared_attribute',
                        sourceSystem: 'Core_Invest_DB', eventId: 'e1'}]->(prop)
            CREATE (p2)-[:CONNECTED_TO {tier: 'T4', source: 'shared_attribute',
                        sourceSystem: 'Core_Invest_DB', eventId: 'e2'}]->(prop)
            CREATE (p2)-[:HAS_ROLE_ON {role: 'BORROWER', tier: 'NEW', source: 'event_role',
                        sourceSystem: 'Core_Invest_DB', eventId: 'e2'}]->(loan)
            """
        )
    )


class TestPartyAnchor:
    def test_cross_role_exposure_aggregates(self, clean_graph, bedrock_client):
        """FR-13/§8 step 6: Patricia's full exposure — every role, every loan,
        every property — from one search, with roles distinguishable."""
        post_all(bedrock_client, curated("HIGH_CONNECTIVITY_NEGATIVE"))
        result = bedrock_client.get(
            "/explore", params={"anchorType": "party", "q": "Patricia Morrison"}
        ).json()

        assert result["anchor"]["nodeType"] == "Party"
        by_type = {}
        for node in result["nodes"]:
            by_type.setdefault(node["nodeType"], []).append(node)
        assert len(by_type["Party"]) == 1
        assert len(by_type["Loan"]) == 6
        assert len(by_type["Property"]) == 6

        role_edges = [e for e in result["edges"] if e["type"] == "HAS_ROLE_ON"]
        assert len(role_edges) == 6
        assert {e["role"] for e in role_edges} == {
            "BORROWER", "KEY_BORROWER_PRINCIPAL", "SPONSOR",
        }
        assert all(e["sourceSystem"] and e["eventId"] for e in result["edges"])
        assert result["flags"] == []  # legitimate breadth — no signal (FR-25e)
        assert result["guards"] == []

        # FR-23: party carries its type and the tiers that assembled it
        party = by_type["Party"][0]
        assert party["properties"]["partyType"] == "INDIVIDUAL"
        assert "resolutionTiers" in party["properties"]
        assert "embedding" not in party["properties"]

    def test_anchor_by_party_id_matches_name_lookup(self, clean_graph, bedrock_client):
        post_all(bedrock_client, curated("HIGH_CONNECTIVITY_NEGATIVE"))
        by_name = bedrock_client.get(
            "/explore", params={"anchorType": "party", "q": "PATRICIA MORRISON"}
        ).json()
        by_id = bedrock_client.get(
            "/explore", params={"anchorType": "party", "q": by_name["anchor"]["id"]}
        ).json()
        assert by_id["anchor"]["id"] == by_name["anchor"]["id"]
        assert len(by_id["nodes"]) == len(by_name["nodes"])


class TestLoanAnchor:
    def test_loan_scoped_party_graph(self, clean_graph, bedrock_client):
        post_all(bedrock_client, curated("T2_VARIANT_CLUSTER"))
        result = bedrock_client.get(
            "/explore", params={"anchorType": "loan", "q": "MF-111111"}
        ).json()
        assert result["anchor"]["nodeType"] == "Loan"
        parties = [n for n in result["nodes"] if n["nodeType"] == "Party"]
        assert len(parties) == 1
        # Hop 2 from the loan: the party's other loans and properties
        loans = {n["id"] for n in result["nodes"] if n["nodeType"] == "Loan"}
        assert loans == {"MF-111111", "MF-222222", "MF-333333"}


class TestPropertyAnchorAndFlags:
    def test_shared_address_carries_flag_references(self, clean_graph, bedrock_client):
        """§8 step 7: the fan-out cluster's shared address — three parties,
        each flagged with signal id + pattern type only (FR-15)."""
        post_all(bedrock_client, curated("FANOUT_POSITIVE"))
        result = bedrock_client.get(
            "/explore",
            params={"anchorType": "property", "q": "777 Risk Avenue, Las Vegas, NV 89109"},
        ).json()
        assert result["anchor"]["nodeType"] == "Property"
        parties = [n for n in result["nodes"] if n["nodeType"] == "Party"]
        assert len(parties) == 3

        assert len(result["flags"]) == 3
        for flag in result["flags"]:
            assert set(flag.keys()) == {"partyId", "signalId", "patternType"}
            assert flag["patternType"] == "attribute_fanout"


class TestDegreeGuard:
    def test_high_degree_anchor_returns_marker_not_paths(self, clean_graph, app_client):
        """§8 step 8: summary marker instead of thousands of paths."""
        clean_graph.execute_write(
            lambda tx: tx.run(
                "CREATE (prop:Property {id: 'AGENT ADDR', normalizedAddress: 'AGENT ADDR', "
                "rawAddress: 'Agent Addr'}) "
                "WITH prop UNWIND range(1, 250) AS i "
                "CREATE (p:Party {id: 'gp-' + toString(i), partyType: 'ENTITY', "
                "normalizedName: 'GEN ' + toString(i), displayName: 'Gen ' + toString(i)}) "
                "CREATE (p)-[:CONNECTED_TO {tier: 'T4', source: 'shared_attribute', "
                "sourceSystem: 'Core_Invest_DB', eventId: 'seed-' + toString(i)}]->(prop)"
            )
        )
        result = app_client.get(
            "/explore", params={"anchorType": "property", "q": "AGENT ADDR"}
        ).json()
        [guard] = result["guards"]
        assert guard == {
            "nodeId": "AGENT ADDR",
            "nodeType": "Property",
            "label": "Agent Addr",
            "degree": 250,
            "expanded": False,
        }
        assert [n["id"] for n in result["nodes"]] == ["AGENT ADDR"]
        assert result["edges"] == []


class TestTraversalBounds:
    def test_two_hop_limit(self, clean_graph, app_client):
        build_mini_graph(clean_graph)
        result = app_client.get(
            "/explore", params={"anchorType": "party", "q": "p1"}
        ).json()
        ids = {n["id"]: n["hop"] for n in result["nodes"]}
        assert ids == {"p1": 0, "9 SHARED CT": 1, "p2": 2}
        assert "MF-X1" not in ids  # hop 3 — out of bounds (FR-13)

    def test_edges_oriented_from_party(self, clean_graph, app_client):
        build_mini_graph(clean_graph)
        result = app_client.get(
            "/explore", params={"anchorType": "property", "q": "9 SHARED CT"}
        ).json()
        for edge in result["edges"]:
            assert edge["source"].startswith("p")  # Party end is always source


class TestReadOnly:
    def test_explore_writes_nothing_and_raises_nothing(self, clean_graph, app_client):
        """FR-16."""
        build_mini_graph(clean_graph)
        before = clean_graph.execute_read(
            lambda tx: tx.run(
                "MATCH (n) WITH count(n) AS nodes "
                "MATCH ()-[r]->() RETURN nodes, count(r) AS rels"
            ).single()
        )
        app_client.get("/explore", params={"anchorType": "party", "q": "p1"})
        after = clean_graph.execute_read(
            lambda tx: tx.run(
                "MATCH (n) WITH count(n) AS nodes "
                "MATCH ()-[r]->() RETURN nodes, count(r) AS rels"
            ).single()
        )
        assert dict(before) == dict(after)
        signals = clean_graph.execute_read(
            lambda tx: tx.run("MATCH (s:Signal) RETURN count(s) AS n").single()["n"]
        )
        assert signals == 0


class TestErrorsAndLatency:
    def test_unknown_anchor_404(self, clean_graph, app_client):
        resp = app_client.get(
            "/explore", params={"anchorType": "party", "q": "Nobody Here"}
        )
        assert resp.status_code == 404

    def test_latency_informal(self, clean_graph, app_client):
        """NFR-5: p50 < 500ms — informal check, generous bound for CI noise."""
        build_mini_graph(clean_graph)
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            app_client.get("/explore", params={"anchorType": "party", "q": "p1"})
            timings.append(time.perf_counter() - start)
        timings.sort()
        assert timings[2] < 0.5, f"p50 {timings[2]:.3f}s exceeds 500ms"
