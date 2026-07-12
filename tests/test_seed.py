"""Seed loader and demo reset (FR-24, FR-25)."""


def party_count_by_name(graph, normalized_name: str) -> int:
    return graph.execute_read(
        lambda tx: tx.run(
            "MATCH (p:Party {normalizedName: $name}) RETURN count(p) AS n",
            name=normalized_name,
        ).single()["n"]
    )


class TestSeedStructuralInvariants:
    """Hash-adapter run: asserts only what deterministic tiers guarantee."""

    def test_reset_loads_curated_dataset(self, clean_graph, app_client):
        summary = app_client.post("/admin/reset").json()
        assert summary["events"] == 274
        assert summary["duplicatesAbsorbed"] == 1  # FR-25h
        assert summary["rawRecords"] == 273

        # Deterministic (T1/T2) merges hold regardless of embedding adapter:
        assert party_count_by_name(clean_graph, "JONATHAN SMITH") == 1  # FR-25a
        assert party_count_by_name(clean_graph, "MERIDIAN MULTIFAMILY HOLDINGS LLC") == 1
        assert party_count_by_name(clean_graph, "JOHN TIERONE") == 1  # T1 SSN
        assert party_count_by_name(clean_graph, "APEX PROPERTY MANAGEMENT") == 1

        # FR-25f: the planted fan-out fired; FR-25g: the agent address didn't stay raised
        [signal] = app_client.get("/signals").json()
        assert signal["patternType"] == "attribute_fanout"
        assert "777 RISK AVE" in signal["attributeId"]

        # FR-25g: 250 registrations connected to the agent address
        degree = clean_graph.execute_read(
            lambda tx: tx.run(
                "MATCH (prop:Property)<-[c:CONNECTED_TO]-() "
                "WHERE prop.id CONTAINS 'CORPORATION TRUST CENTER' "
                "RETURN count(c) AS n"
            ).single()["n"]
        )
        assert degree == 250

    def test_reset_clears_prior_state(self, clean_graph, app_client):
        app_client.post(
            "/events",
            json={
                "sourceSystem": "LoanSphere_Origination",
                "eventId": "test-pre-reset",
                "partyType": "INDIVIDUAL",
                "firstName": "Gone",
                "lastName": "Soon",
                "address": "1 Vanish Way, Nowhere, KS 66002",
            },
        )
        summary = app_client.post("/admin/reset").json()
        assert summary["clearedNodes"] > 0
        leftover = clean_graph.execute_read(
            lambda tx: tx.run(
                "MATCH (r:RawRecord {eventId: 'test-pre-reset'}) RETURN count(r) AS n"
            ).single()["n"]
        )
        assert leftover == 0
        # Streams were truncated: outcomes only from the fresh seed
        outcome_lines = (
            (app_client.streams_dir / "resolution-outcome.jsonl").read_text().splitlines()
        )
        assert len(outcome_lines) == 273

    def test_reset_is_repeatable(self, clean_graph, app_client):
        first = app_client.post("/admin/reset").json()
        second = app_client.post("/admin/reset").json()
        for key in ("events", "duplicatesAbsorbed", "parties", "rawRecords", "raisedSignals"):
            assert first[key] == second[key], key


class TestSeedResolutionExpectations:
    """Bedrock run: the FR-25 party arithmetic under calibrated thresholds."""

    def test_full_seed_party_counts(self, clean_graph, bedrock_client):
        summary = bedrock_client.post("/admin/reset").json()
        # 273 unique events → 262 parties: cluster 1, entity-suffix 1, SSN 1,
        # fuzzy 1, address-less 1, type-isolation 2, multi-source 1,
        # high-connectivity 1, fan-out 3, degree-guard 250.
        assert summary["parties"] == 262
        assert summary["raisedSignals"] == 1

        assert party_count_by_name(clean_graph, "PATRICIA MORRISON") == 1
        assert party_count_by_name(clean_graph, "ROBERT CHEN") == 1  # absorbed Robb
        assert party_count_by_name(clean_graph, "ROBB CHEN") == 0
